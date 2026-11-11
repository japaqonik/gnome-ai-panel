"""Fixtures for integration tests that run the application as a subprocess.

``app_process`` starts ``python -m app`` on the test's display (Xvfb from ``make test-py``)
but on a private D-Bus session bus started for the test, with HOME/XDG_* from
``isolated_env``, a fresh ``XDG_RUNTIME_DIR`` (mode 0700) and ``GIO_USE_VFS=local``. Services
the bus activates (portals, keyring, a11y) inherit that environment, so nothing reaches the
user's session bus, keyring or ``/run/user/<uid>``.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

APP_ID = "pl.local.AiPanel"
OBJECT_PATH = "/pl/local/AiPanel"
READY_TIMEOUT = 15.0
REPO_ROOT = Path(__file__).resolve().parents[2]

# Variables of the developer's session that must not leak into the app under test.
SESSION_VARS = (
    "DBUS_SESSION_BUS_ADDRESS",
    "WAYLAND_DISPLAY",
    "GNOME_KEYRING_CONTROL",
    "SSH_AUTH_SOCK",
    "SESSION_MANAGER",
    "AT_SPI_BUS_ADDRESS",
)


def _require_tools() -> None:
    if not os.environ.get("DISPLAY"):
        pytest.skip("needs an X display (run through make test-py)")
    for tool in ("dbus-daemon", "gapplication", "gdbus"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not installed")


@dataclass
class PrivateBus:
    address: str
    pid: int
    env: dict[str, str]

    def stop(self) -> None:
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.kill(self.pid, signal.SIGKILL)


@pytest.fixture
def app_env(isolated_env: dict[str, Path], tmp_path: Path) -> dict[str, str]:
    """Environment for the app: isolated XDG dirs, runtime dir, X11 backend, debug actions."""
    _require_tools()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    runtime.chmod(0o700)
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.update({var: str(path) for var, path in isolated_env.items()})
    env.update(
        {
            "XDG_RUNTIME_DIR": str(runtime),
            "GIO_USE_VFS": "local",
            "GDK_BACKEND": "x11",
            "AI_PANEL_DEBUG": "1",
            "WEBKIT_DISABLE_COMPOSITING_MODE": "1",
            "LIBGL_ALWAYS_SOFTWARE": "1",
            "NO_AT_BRIDGE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


@pytest.fixture
def private_bus(app_env: dict[str, str]) -> Iterator[PrivateBus]:
    """A session bus of its own; ``app_env`` gains its ``DBUS_SESSION_BUS_ADDRESS``."""
    out = subprocess.run(
        ["dbus-daemon", "--session", "--fork", "--nopidfile", "--print-address=1", "--print-pid=1"],
        env=app_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout.split()
    address, pid = out[0], int(out[1])
    assert address.startswith("unix:"), out
    app_env["DBUS_SESSION_BUS_ADDRESS"] = address
    bus = PrivateBus(address=address, pid=pid, env=app_env)
    try:
        yield bus
    finally:
        bus.stop()


@dataclass
class AppProcess:
    """Handle of one running ``python -m app`` started by the ``app_process`` fixture."""

    proc: subprocess.Popen
    env: dict[str, str]
    log: Path
    stderr_path: Path

    @property
    def pid(self) -> int:
        return self.proc.pid

    def run(self, *argv: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(argv), env=self.env, capture_output=True, text=True, timeout=timeout
        )

    def action(self, name: str) -> None:
        result = self.run("gapplication", "action", APP_ID, name)
        assert result.returncode == 0, result.stderr

    def visible(self) -> bool:
        result = self.run(
            "gdbus", "call", "--session", "-d", APP_ID, "-o", OBJECT_PATH,
            "-m", "org.gtk.Actions.Describe", "visible",
        )  # fmt: skip
        assert result.returncode == 0, result.stderr
        match = re.search(r"\[<(true|false)>\]", result.stdout)
        assert match, result.stdout
        return match.group(1) == "true"

    def name_owner_pid(self) -> int:
        result = self.run(
            "gdbus", "call", "--session", "-d", "org.freedesktop.DBus",
            "-o", "/org/freedesktop/DBus",
            "-m", "org.freedesktop.DBus.GetConnectionUnixProcessID", APP_ID,
        )  # fmt: skip
        assert result.returncode == 0, result.stderr
        match = re.search(r"\(uint32 (\d+),\)", result.stdout)
        assert match, result.stdout
        return int(match.group(1))

    def stderr_text(self) -> str:
        return self.stderr_path.read_text(errors="replace")


def _wait_for_ready(app: AppProcess, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app.log.exists() and "ui ready" in app.log.read_text(errors="replace"):
            return
        if app.proc.poll() is not None:
            pytest.fail(f"app exited with {app.proc.returncode}:\n{app.stderr_text()}")
        time.sleep(0.05)
    pytest.fail(f"no 'ui ready' within {timeout} s:\n{app.stderr_text()}")


def _stop(app: AppProcess) -> None:
    if app.proc.poll() is None:
        try:
            app.run("gapplication", "action", APP_ID, "quit", timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            app.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app.proc.terminate()
            try:
                app.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                app.proc.kill()
                app.proc.wait()


@pytest.fixture
def app_process(
    private_bus: PrivateBus, isolated_env: dict[str, Path], tmp_path: Path
) -> Iterator[Callable[..., AppProcess]]:
    """Factory: ``app_process(*args)`` starts ``python -m app *args`` and waits for ``ui ready``.

    Every started process is stopped after the test (``quit``, then SIGTERM, then SIGKILL).
    """
    started: list[AppProcess] = []
    env = private_bus.env

    def start(*args: str, wait_ready: bool = True) -> AppProcess:
        index = len(started)
        stderr_path = tmp_path / f"app-{index}.stderr"
        with stderr_path.open("wb") as stderr:
            proc = subprocess.Popen(
                [sys.executable, "-m", "app", *args],
                cwd=REPO_ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stderr,
                stderr=subprocess.STDOUT,
            )
        app = AppProcess(
            proc=proc,
            env=env,
            log=isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel" / "app.log",
            stderr_path=stderr_path,
        )
        started.append(app)
        if wait_ready:
            _wait_for_ready(app, READY_TIMEOUT)
        return app

    try:
        yield start
    finally:
        for app in reversed(started):
            _stop(app)
