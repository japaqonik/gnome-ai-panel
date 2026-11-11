"""PanelWindow under Xvfb: window properties, hide-on-close and the real page -> bridge path.

Added by the tester for S1-T2. The application object is never registered on D-Bus.
"""

import os
import time

import pytest

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("needs a display (run through make test-py)", allow_module_level=True)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from app.bridge import Bridge  # noqa: E402
from app.window import DEFAULT_HEIGHT, DEFAULT_WIDTH, INDEX_HTML  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.filterwarnings("ignore::DeprecationWarning")]


def _iterate_until(predicate, timeout: float = 15.0) -> bool:
    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        ctx.iteration(False)
        time.sleep(0.005)
    return predicate()


class RecordingBridge(Bridge):
    def __init__(self) -> None:
        self.ready_calls = 0
        self.messages: list[dict] = []
        super().__init__(on_ready=self._ready)

    def _ready(self) -> None:
        self.ready_calls += 1

    def handle(self, message: dict) -> None:
        self.messages.append(message)
        super().handle(message)


@pytest.fixture
def window(isolated_env):
    Adw.init()
    from app.window import PanelWindow

    app = Adw.Application(application_id=None)
    bridge = RecordingBridge()
    win = PanelWindow(app, bridge)
    yield win
    win.destroy()
    _iterate_until(lambda: False, timeout=0.1)


def test_window_properties(window) -> None:
    assert window.get_decorated() is False
    assert window.get_default_size() == (DEFAULT_WIDTH, DEFAULT_HEIGHT) == (480, 900)
    assert window.get_hide_on_close() is True
    assert window.webview.get_uri() == INDEX_HTML.as_uri()
    assert window.webview.get_uri().startswith("file://")


def test_developer_extras_off_by_default(window) -> None:
    assert window.webview.get_settings().get_enable_developer_extras() is False


def test_page_sends_ready_through_bridge(window) -> None:
    assert _iterate_until(lambda: window.bridge.ready_calls >= 1), "page never sent ready"
    assert window.bridge.messages[0] == {"type": "ready"}


def test_close_hides_instead_of_destroying(window) -> None:
    window.present()
    assert _iterate_until(window.get_visible)
    window.close()
    assert _iterate_until(lambda: not window.get_visible())
    # Still usable afterwards: can be shown again.
    window.present()
    assert _iterate_until(window.get_visible)
    assert window in Gtk.Window.list_toplevels()


@pytest.mark.parametrize(
    "script",
    [
        "window.webkit.messageHandlers.bridge.postMessage('plain string')",
        "window.webkit.messageHandlers.bridge.postMessage(42)",
        "window.webkit.messageHandlers.bridge.postMessage({})",
        "window.webkit.messageHandlers.bridge.postMessage({type: ''})",
        "window.webkit.messageHandlers.bridge.postMessage({type: 5})",
        "window.webkit.messageHandlers.bridge.postMessage([{type: 'ready'}])",
        "window.webkit.messageHandlers.bridge.postMessage(null)",
    ],
)
def test_invalid_messages_from_page_are_dropped(window, script) -> None:
    assert _iterate_until(lambda: window.bridge.ready_calls >= 1)
    before = list(window.bridge.messages)
    done: list[bool] = []
    window.webview.evaluate_javascript(
        script + "; true", -1, None, None, None, lambda *_a: done.append(True)
    )
    assert _iterate_until(lambda: bool(done))
    _iterate_until(lambda: False, timeout=0.3)
    assert window.bridge.messages == before
    assert window.bridge.ready_calls == 1


def test_valid_message_from_page_is_routed(window) -> None:
    assert _iterate_until(lambda: window.bridge.ready_calls >= 1)
    window.webview.evaluate_javascript(
        "window.webkit.messageHandlers.bridge.postMessage({type: 'ping', n: 1}); true",
        -1,
        None,
        None,
        None,
        None,
    )
    assert _iterate_until(lambda: {"type": "ping", "n": 1} in window.bridge.messages)
