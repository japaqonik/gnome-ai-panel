"""The application as a process: D-Bus actions, single instance and quit (S1-T3).

Runs ``python -m app`` on a private session bus (see ``conftest.py``) and drives it with
``gapplication`` / ``gdbus`` like the UAT scripts do.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

APP_ID = "pl.local.AiPanel"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_toggle_switches_visible(app_process):
    app = app_process("--background")
    assert app.visible() is False
    app.action("toggle")
    assert app.visible() is True
    app.action("toggle")
    assert app.visible() is False


def test_show_and_hide(app_process):
    app = app_process("--background")
    app.action("show")
    assert app.visible() is True
    app.action("show")
    assert app.visible() is True
    app.action("hide")
    assert app.visible() is False


def test_actions_are_listed_on_the_bus(app_process):
    app = app_process("--background")
    # `gapplication list-actions` needs an installed .desktop file, so ask D-Bus directly.
    result = app.run(
        "gdbus", "call", "--session", "-d", APP_ID, "-o", "/pl/local/AiPanel",
        "-m", "org.gtk.Actions.List",
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    names = set(re.findall(r"'([a-z-]+)'", result.stdout))
    assert names >= {"toggle", "show", "hide", "new-chat", "quit", "visible"}


def test_second_start_hands_over_to_running_instance(app_process):
    first = app_process("--background")
    assert first.name_owner_pid() == first.pid

    second = subprocess.run(
        [sys.executable, "-m", "app", "--background"],
        cwd=REPO_ROOT,
        env=first.env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=15,
    )
    assert second.returncode == 0, second.stderr
    assert first.proc.poll() is None, "first instance must keep running"
    assert first.name_owner_pid() == first.pid
    # --background on the running instance must not show its window.
    assert first.visible() is False

    # Without --background the second start activates the running instance.
    third = subprocess.run(
        [sys.executable, "-m", "app"],
        cwd=REPO_ROOT,
        env=first.env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=15,
    )
    assert third.returncode == 0, third.stderr
    assert first.name_owner_pid() == first.pid
    assert first.visible() is True
    assert first.log.read_text().count("ui ready") == 1


def test_quit_ends_process_within_5_seconds(app_process):
    app = app_process("--background")
    started = time.monotonic()
    app.action("quit")
    assert app.proc.wait(timeout=5) == 0
    assert time.monotonic() - started <= 5
    result = app.run(
        "gdbus", "call", "--session", "-d", "org.freedesktop.DBus",
        "-o", "/org/freedesktop/DBus", "-m", "org.freedesktop.DBus.NameHasOwner", APP_ID,
    )  # fmt: skip
    assert "(false,)" in result.stdout


def test_app_environment_is_isolated(app_process, isolated_env):
    app = app_process("--background")
    runtime = app.env["XDG_RUNTIME_DIR"]
    assert runtime.startswith(str(isolated_env["HOME"].parent))
    assert app.env["GIO_USE_VFS"] == "local"
    assert app.env["DBUS_SESSION_BUS_ADDRESS"] != os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    environ = Path(f"/proc/{app.pid}/environ").read_bytes().split(b"\0")
    assert f"XDG_RUNTIME_DIR={runtime}".encode() in environ
    assert b"GIO_USE_VFS=local" in environ
