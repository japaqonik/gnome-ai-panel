"""Actions of ``pl.local.AiPanel`` without a window and without registering on D-Bus."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from gi.repository import GLib

from app.main import APP_ID, SIMPLE_ACTIONS, STATE_ACTIONS, AiPanelApplication


@pytest.fixture
def application() -> AiPanelApplication:
    app = AiPanelApplication()
    assert not app.get_is_registered()
    return app


def test_application_id(application: AiPanelApplication) -> None:
    assert application.get_application_id() == APP_ID == "pl.local.AiPanel"


EXPECTED_ACTIONS = ["toggle", "show", "hide", "new-chat", "quit", "visible"]


def test_registered_actions(application: AiPanelApplication) -> None:
    # Gio.ActionGroup.list_actions() needs a registered application; the ActionMap
    # lookup does not, so check each expected name plus the module's declared list.
    assert sorted(SIMPLE_ACTIONS + STATE_ACTIONS) == sorted(EXPECTED_ACTIONS)
    for name in EXPECTED_ACTIONS:
        assert application.lookup_action(name) is not None, name
    assert application.lookup_action("debug-dump") is None


@pytest.mark.parametrize("name", ["toggle", "show", "hide", "new-chat", "quit"])
def test_simple_actions_are_stateless_without_parameter(
    application: AiPanelApplication, name: str
) -> None:
    action = application.lookup_action(name)
    assert action.get_state() is None
    assert action.get_parameter_type() is None
    assert action.get_enabled()


def test_visible_is_boolean_state_initially_false(application: AiPanelApplication) -> None:
    action = application.lookup_action("visible")
    assert action.get_state_type().equal(GLib.VariantType.new("b"))
    assert action.get_state().get_boolean() is False
    assert action.get_parameter_type() is None


def test_visible_is_read_only(application: AiPanelApplication) -> None:
    action = application.lookup_action("visible")
    action.change_state(GLib.Variant("b", True))
    action.activate(None)
    assert action.get_state().get_boolean() is False


@pytest.mark.parametrize("name", ["toggle", "show", "hide", "new-chat"])
def test_actions_without_window_do_not_fail(application: AiPanelApplication, name: str) -> None:
    application.lookup_action(name).activate(None)
    assert application.lookup_action("visible").get_state().get_boolean() is False


def _env_without_display(isolated_env: dict[str, Path]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env["GDK_BACKEND"] = "x11"  # never fall back to the developer's Wayland session
    return env


def test_import_main_needs_no_display(isolated_env: dict[str, Path], repo_root: Path) -> None:
    code = (
        "import app.main\n"
        "from gi.repository import Gtk\n"
        "assert Gtk.Window.list_toplevels() == [], Gtk.Window.list_toplevels()\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=_env_without_display(isolated_env),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_help_lists_background_option(isolated_env: dict[str, Path], repo_root: Path) -> None:
    # --help is handled locally by GOption: no window, no D-Bus registration.
    proc = subprocess.run(
        [sys.executable, "-m", "app", "--help"],
        cwd=repo_root,
        env=_env_without_display(isolated_env),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--background" in proc.stdout
