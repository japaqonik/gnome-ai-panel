"""Integration tests of the keyring (``LibsecretStore`` and ``secret`` CLI commands).

Nothing here talks to the developer's session bus or keyring. Every test starts its own
``dbus-daemon`` with HOME/XDG_* in ``tmp_path``, a fresh ``XDG_RUNTIME_DIR`` and no
``DISPLAY``; the keyring tests additionally start a private ``gnome-keyring-daemon`` on that
bus (keyring files under ``tmp_path``). The code under test runs in subprocesses, because
GIO caches the session bus connection per process.

The keyring tests are skipped when no Secret Service can be started (``gnome-keyring-daemon``
missing or not answering).
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).resolve().parent / "libsecret_probe.py"
SESSION_VARS = (
    "DBUS_SESSION_BUS_ADDRESS",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "GNOME_KEYRING_CONTROL",
    "SSH_AUTH_SOCK",
    "SESSION_MANAGER",
    "AT_SPI_BUS_ADDRESS",
    "XAUTHORITY",
)
KEYRING_PASSWORD = b"test-password"
NO_SERVICE = "brak usługi Secret Service"


@dataclass
class Bus:
    env: dict[str, str]
    pid: int


def _kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    os.kill(pid, signal.SIGKILL)


@pytest.fixture
def private_env(isolated_env: dict[str, Path], tmp_path: Path) -> dict[str, str]:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    env = {k: v for k, v in os.environ.items() if k not in SESSION_VARS}
    env.update({var: str(path) for var, path in isolated_env.items()})
    env.update(
        {
            "XDG_RUNTIME_DIR": str(runtime),
            "GIO_USE_VFS": "local",
            "PYTHONPATH": str(REPO_ROOT),
            "LC_ALL": "C.UTF-8",
        }
    )
    return env


@pytest.fixture
def bus(private_env: dict[str, str]) -> Iterator[Bus]:
    if shutil.which("dbus-daemon") is None:
        pytest.skip("dbus-daemon not installed")
    out = subprocess.run(
        ["dbus-daemon", "--session", "--fork", "--nopidfile", "--print-address=1", "--print-pid=1"],
        env=private_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout.split()
    address, pid = out[0], int(out[1])
    assert address.startswith("unix:"), out
    env = dict(private_env, DBUS_SESSION_BUS_ADDRESS=address)
    try:
        yield Bus(env=env, pid=pid)
    finally:
        _kill(pid)


def _secrets_owned(env: dict[str, str]) -> bool:
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "-d",
            "org.freedesktop.DBus",
            "-o",
            "/org/freedesktop/DBus",
            "-m",
            "org.freedesktop.DBus.NameHasOwner",
            "org.freedesktop.secrets",
        ],  # fmt: skip
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return "true" in result.stdout


@pytest.fixture
def keyring_bus(bus: Bus) -> Iterator[Bus]:
    """``bus`` with a private, unlocked ``gnome-keyring-daemon`` owning the secrets name."""
    daemon = shutil.which("gnome-keyring-daemon")
    if daemon is None or shutil.which("gdbus") is None:
        pytest.skip("brak usługi Secret Service: gnome-keyring-daemon/gdbus not installed")
    proc = subprocess.Popen(
        [daemon, "--foreground", "--unlock", "--components=secrets"],
        env=bus.env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert proc.stdin is not None
        proc.stdin.write(KEYRING_PASSWORD)
        proc.stdin.close()
        deadline = time.monotonic() + 10
        while not _secrets_owned(bus.env):
            if proc.poll() is not None or time.monotonic() > deadline:
                pytest.skip("brak usługi Secret Service: private keyring daemon did not start")
            time.sleep(0.1)
        yield bus
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def cli(env: dict[str, str], *args: str, stdin: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=REPO_ROOT,
        env=env,
        input=stdin,
        capture_output=True,
        timeout=30,
        check=False,
    )


# -- no Secret Service ---------------------------------------------------------------------


@pytest.mark.parametrize("command", ["set", "has", "delete"])
def test_cli_without_secret_service_on_bus(bus: Bus, command: str) -> None:
    """Done-when of S2-T2: exit code 1 and a message, no traceback. The service must not
    be D-Bus-activated (the private bus could activate gnome-keyring)."""
    result = cli(bus.env, "secret", command, "test-x", stdin=b"abc")
    err = result.stderr.decode()
    assert result.returncode == 1, err
    assert NO_SERVICE in err
    assert "Traceback" not in err
    assert b"abc" not in result.stdout + result.stderr
    assert not _secrets_owned(bus.env), "the Secret Service was activated"


def test_cli_without_session_bus(private_env: dict[str, str], tmp_path: Path) -> None:
    env = dict(private_env, DBUS_SESSION_BUS_ADDRESS=f"unix:path={tmp_path}/no-bus")
    result = cli(env, "secret", "set", "test-x", stdin=b"abc")
    err = result.stderr.decode()
    assert result.returncode == 1, err
    assert NO_SERVICE in err
    assert "Traceback" not in err


def test_make_cli_done_when(bus: Bus) -> None:
    """``printf 'abc' | make cli ARGS="secret set test-x"`` without Secret Service: the CLI
    exits 1 (make reports 2, as for every failing recipe)."""
    if shutil.which("make") is None:
        pytest.skip("make not installed")
    result = subprocess.run(
        ["make", "-s", "cli", "ARGS=secret set test-x"],
        cwd=REPO_ROOT,
        env=bus.env,
        input=b"abc",
        capture_output=True,
        timeout=60,
        check=False,
    )
    err = result.stderr.decode()
    assert result.returncode == 2, err
    assert NO_SERVICE in err
    assert "Traceback" not in err


# -- private keyring -----------------------------------------------------------------------


def test_libsecret_store_roundtrip(keyring_bus: Bus) -> None:
    result = subprocess.run(
        [sys.executable, str(PROBE), "it-name", "it-value"],
        cwd=REPO_ROOT,
        env=keyring_bus.env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data == {
        "has_before": False,
        "get_before": None,
        "has_after_set": True,
        "get_after_set": "it-value",
        "resolve": "it-value",
        "get_after_overwrite": "it-value-2",
        "other_name": None,
        "delete": True,
        "delete_again": False,
        "has_after_delete": False,
    }


def test_cli_secret_commands_with_keyring(keyring_bus: Bus, isolated_env) -> None:
    env = keyring_bus.env
    assert cli(env, "secret", "has", "test-x").returncode == 1
    result = cli(env, "secret", "set", "test-x", stdin=b"abc\n")
    assert result.returncode == 0, result.stderr.decode()
    assert b"abc" not in result.stdout + result.stderr
    assert cli(env, "secret", "has", "test-x").returncode == 0
    assert cli(env, "secret", "delete", "test-x").returncode == 0
    assert cli(env, "secret", "has", "test-x").returncode == 1
    assert cli(env, "secret", "delete", "test-x").returncode == 1
    # The keyring files live in the isolated home, never in the user's one.
    assert (isolated_env["XDG_DATA_HOME"] / "keyrings").is_dir()
