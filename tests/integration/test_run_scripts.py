"""scripts/run-headless.sh and scripts/stop.sh end to end (S1-T3).

``AI_PANEL_RUN_DIR`` points the scripts at ``tmp_path`` so a developer's ``.run/`` and
running instance are left alone. The scripts start their own Xvfb and session bus.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
APP_ID = "pl.local.AiPanel"


@pytest.fixture
def run_dir(tmp_path: Path, isolated_env) -> Path:
    for tool in ("Xvfb", "dbus-daemon", "gapplication", "gdbus"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not installed")
    path = tmp_path / "run"
    yield path
    # Never leave processes behind, even when the test failed half way.
    subprocess.run([SCRIPTS / "stop.sh"], env=_env(path), capture_output=True, timeout=30)


def _env(run_dir: Path) -> dict[str, str]:
    return {**os.environ, "AI_PANEL_RUN_DIR": str(run_dir)}


def _script(name: str, run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [SCRIPTS / name], env=_env(run_dir), capture_output=True, text=True, timeout=60
    )


def _headless_env(run_dir: Path) -> dict[str, str]:
    """Environment after ``source headless.env`` in a clean shell."""
    out = subprocess.run(
        ["bash", "-c", 'set -e; . "$1"; env -0', "bash", str(run_dir / "headless.env")],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        timeout=10,
        check=True,
    ).stdout
    return dict(item.split("=", 1) for item in out.decode().split("\0") if "=" in item)


def _visible(env: dict[str, str]) -> bool:
    result = subprocess.run(
        ["gdbus", "call", "--session", "-d", APP_ID, "-o", "/pl/local/AiPanel",
         "-m", "org.gtk.Actions.Describe", "visible"],
        env=env, capture_output=True, text=True, timeout=10,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    return re.search(r"\[<(true|false)>\]", result.stdout).group(1) == "true"


def _pids(run_dir: Path) -> dict[str, int]:
    return {name: int((run_dir / f"{name}.pid").read_text()) for name in ("app", "xvfb", "dbus")}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); treat it as gone.
    stat = Path(f"/proc/{pid}/stat")
    return stat.exists() and stat.read_text().split()[2] != "Z"


def test_run_headless_show_toggle_and_stop(run_dir: Path):
    started = _script("run-headless.sh", run_dir)
    assert started.returncode == 0, started.stderr
    assert (run_dir / "headless.env").is_file()

    env = _headless_env(run_dir)
    for var in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):  # fmt: skip
        assert env.get(var), var
    assert env["AI_PANEL_DEBUG"] == "1"
    assert env["GDK_BACKEND"] == "x11"
    assert env["GIO_USE_VFS"] == "local"
    assert env["DBUS_SESSION_BUS_ADDRESS"] != os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    assert env["XDG_STATE_HOME"] == str(run_dir / "home" / "state")
    runtime = Path(env["XDG_RUNTIME_DIR"])
    assert runtime.is_dir()
    assert runtime.stat().st_mode & 0o777 == 0o700
    assert not str(runtime).startswith("/run/user/")

    log = run_dir / "home" / "state" / "gnome-ai-panel" / "app.log"
    assert "ui ready" in log.read_text()

    gapp = ["gapplication", "action", APP_ID]
    assert subprocess.run([*gapp, "show"], env=env, timeout=10).returncode == 0
    assert _visible(env) is True
    assert subprocess.run([*gapp, "toggle"], env=env, timeout=10).returncode == 0
    assert _visible(env) is False

    # A second run-headless reuses the running instance.
    again = _script("run-headless.sh", run_dir)
    assert again.returncode == 0, again.stderr
    assert "already running" in again.stderr

    pids = _pids(run_dir)
    stopped = _script("stop.sh", run_dir)
    assert stopped.returncode == 0, stopped.stderr
    deadline = time.monotonic() + 5
    while any(_alive(pid) for pid in pids.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not [name for name, pid in pids.items() if _alive(pid)]
    assert not list(run_dir.glob("*.pid"))
    assert not (run_dir / "headless.env").exists()
    assert not runtime.exists()

    second = _script("stop.sh", run_dir)
    assert second.returncode == 0, second.stderr


def test_stop_without_anything_running(run_dir: Path):
    result = _script("stop.sh", run_dir)
    assert result.returncode == 0, result.stderr


def test_stop_ignores_pid_files_of_unrelated_processes(run_dir: Path):
    run_dir.mkdir()
    bystander = subprocess.Popen(["sleep", "30"])
    try:
        for name in ("app", "xvfb", "dbus"):
            (run_dir / f"{name}.pid").write_text(f"{bystander.pid}\n")
        (run_dir / "runtime-dir").write_text(f"{run_dir}\n")  # not ai-panel-runtime.*
        result = _script("stop.sh", run_dir)
        assert result.returncode == 0, result.stderr
        assert bystander.poll() is None, "stop.sh must not signal a process it did not start"
        assert not list(run_dir.glob("*.pid"))
        assert run_dir.is_dir(), "only mktemp'd ai-panel-runtime.* directories are removed"
    finally:
        bystander.kill()
        bystander.wait()


def test_stop_handles_garbage_pid_files(run_dir: Path):
    run_dir.mkdir()
    (run_dir / "app.pid").write_text("not-a-pid\n")
    (run_dir / "xvfb.pid").write_text("")
    (run_dir / "dbus.pid").write_text("99999999\n")
    result = _script("stop.sh", run_dir)
    assert result.returncode == 0, result.stderr
    assert not list(run_dir.glob("*.pid"))


# --- Added by the tester (S1-T3 test-1) ---


def _wait_gone(pids: dict[str, int], timeout: float = 5) -> list[str]:
    deadline = time.monotonic() + timeout
    while any(_alive(pid) for pid in pids.values()) and time.monotonic() < deadline:
        time.sleep(0.05)
    return [name for name, pid in pids.items() if _alive(pid)]


def _started_children(run_dir: Path) -> list[int]:
    """Pids of live processes started by the scripts for this run dir (inherited env var)."""
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            environ = (proc / "environ").read_bytes()
        except OSError:
            continue
        if f"AI_PANEL_RUN_DIR={run_dir}\0".encode() in environ + b"\0" and _alive(int(proc.name)):
            found.append(int(proc.name))
    return found


def test_run_headless_cleans_up_when_ui_never_gets_ready(run_dir: Path):
    # READY_TIMEOUT=0: wait_ready gives up at once, so the failure path must tidy everything.
    env = {**_env(run_dir), "READY_TIMEOUT": "0"}
    result = subprocess.run(
        [SCRIPTS / "run-headless.sh"], env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 1, result.stderr
    assert "no 'ui ready'" in result.stderr
    assert not list(run_dir.glob("*.pid"))
    assert not (run_dir / "headless.env").exists()
    assert not (run_dir / "runtime-dir").exists()
    deadline = time.monotonic() + 5
    while _started_children(run_dir) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _started_children(run_dir) == []


def test_stop_after_app_crash_still_stops_xvfb_and_bus(run_dir: Path):
    started = _script("run-headless.sh", run_dir)
    assert started.returncode == 0, started.stderr
    runtime = Path((run_dir / "runtime-dir").read_text().strip())
    pids = _pids(run_dir)
    os.kill(pids["app"], 9)
    assert not _wait_gone({"app": pids["app"]})

    stopped = _script("stop.sh", run_dir)
    assert stopped.returncode == 0, stopped.stderr
    assert not _wait_gone(pids)
    assert not list(run_dir.glob("*.pid"))
    assert not (run_dir / "headless.env").exists()
    assert not runtime.exists()


def test_run_refuses_while_headless_instance_runs(run_dir: Path):
    started = _script("run-headless.sh", run_dir)
    assert started.returncode == 0, started.stderr
    app_pid = _pids(run_dir)["app"]
    # run.sh must bail out before it starts anything (it never reaches the real session bus).
    result = _script("run.sh", run_dir)
    assert result.returncode == 1
    assert "headless instance is running" in result.stderr
    assert _pids(run_dir)["app"] == app_pid
    assert _alive(app_pid)


def test_headless_env_does_not_change_home_and_hides_wayland(run_dir: Path):
    started = _script("run-headless.sh", run_dir)
    assert started.returncode == 0, started.stderr
    out = subprocess.run(
        ["bash", "-c", '. "$1"; printf "%s|%s" "$HOME" "${WAYLAND_DISPLAY-unset}"', "bash",
         str(run_dir / "headless.env")],
        env={"PATH": os.environ["PATH"], "HOME": "/home/sentinel", "WAYLAND_DISPLAY": "wl-9"},
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout  # fmt: skip
    assert out == "/home/sentinel|unset"
    # The app itself runs with the isolated HOME and runtime dir.
    environ = Path(f"/proc/{_pids(run_dir)['app']}/environ").read_bytes().split(b"\0")
    assert f"HOME={run_dir / 'home'}".encode() in environ
    assert b"GIO_USE_VFS=local" in environ
    assert not any(e.startswith(b"XDG_RUNTIME_DIR=/run/user/") for e in environ)
