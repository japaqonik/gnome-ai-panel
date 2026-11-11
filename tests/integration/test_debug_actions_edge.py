"""More GUI checks of the debug actions and the link policy (tester additions, S3-T4).

Same setup as ``test_debug_actions.py``: the app on a private bus, ``AI_PANEL_URI_LOG`` so
no browser or mail client is ever started.
"""

import time

import pytest

from tests.integration.test_debug_actions import (
    DEBUG_ACTIONS,
    FAKE_CONFIG,
    INDEX_URI,
    action,
    dump,
    listed_actions,
    turn_over,
    wait_dump,
)

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("value", ["0", "true", "yes", ""])
def test_debug_actions_need_exactly_1(app_process, app_env, value) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_DEBUG"] = value
    app = app_process("--background")
    names = listed_actions(app)
    assert not names & DEBUG_ACTIONS
    assert {"toggle", "show", "hide", "new-chat", "quit"} <= names


def _wait_file(path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)


def test_mailto_is_launched_and_file_link_is_blocked(app_process, app_env, tmp_path) -> None:
    uri_log = tmp_path / "uri.log"
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_URI_LOG"] = str(uri_log)
    app = app_process("--background")

    action(app, "debug-send", "[plik](file:///etc/passwd)")
    wait_dump(app, lambda s: turn_over(s, 1))
    action(app, "debug-click", "a[data-external]")
    time.sleep(0.5)
    assert not uri_log.exists()
    assert dump(app)["uri"] == INDEX_URI

    action(app, "new-chat")
    action(app, "debug-send", "[poczta](mailto:someone@example.com)")
    wait_dump(app, lambda s: turn_over(s, 1) and "mailto:" in s["messages"][-1]["html"])
    action(app, "debug-click", "a[data-external]")
    _wait_file(uri_log)
    assert uri_log.read_text(encoding="utf-8") == "mailto:someone@example.com\n"
    assert dump(app)["uri"] == INDEX_URI


def test_target_blank_link_opens_no_window_and_no_navigation(
    app_process, app_env, tmp_path
) -> None:
    uri_log = tmp_path / "uri.log"
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_URI_LOG"] = str(uri_log)
    app = app_process("--background")

    action(app, "debug-send", '<a href="https://example.org/" target="_blank">nowe okno</a>')
    wait_dump(app, lambda s: turn_over(s, 1) and "example.org" in s["messages"][-1]["html"])
    action(app, "debug-click", 'a[href="https://example.org/"]')
    _wait_file(uri_log)
    # At most one launch, to the link itself; the page stays where it was.
    assert uri_log.read_text(encoding="utf-8") == "https://example.org/\n"
    state = dump(app)
    assert state["uri"] == INDEX_URI
    assert state["messages"][-1]["role"] == "assistant"
    assert app.proc.poll() is None


def test_debug_send_passes_special_characters_verbatim(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    text = "a 'b' \"c\" \\ </script><!-- \u2028 ${x} `y`\nz"
    action(app, "debug-send", text)
    state = wait_dump(app, lambda s: turn_over(s, 1))
    users = [m for m in state["messages"] if m["role"] == "user"]
    assert [m["text"] for m in users] == [text]
    assert state["uri"] == INDEX_URI
