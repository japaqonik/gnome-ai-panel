import json
import logging
import re

import pytest

from app import bridge
from app.window import INDEX_HTML, UI_DIR


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json",
        "[]",
        '"ready"',
        "{}",
        '{"type": 1}',
        '{"type": ""}',
        '{"kind": "ready"}',
    ],
)
def test_invalid_messages_are_dropped(raw) -> None:
    assert bridge.parse_message(raw) is None


def test_oversized_message_dropped(monkeypatch) -> None:
    monkeypatch.setattr(bridge, "MAX_MESSAGE_BYTES", 10)
    assert bridge.parse_message(json.dumps({"type": "ready", "x": "y" * 20})) is None


def test_valid_message() -> None:
    assert bridge.parse_message('{"type": "ready", "a": 1}') == {"type": "ready", "a": 1}


def test_ready_logs_and_calls_back(caplog) -> None:
    calls = []
    b = bridge.Bridge(on_ready=lambda: calls.append(1))
    with caplog.at_level(logging.INFO, logger="app.bridge"):
        b.handle({"type": "ready"})
    assert calls == [1]
    assert "ui ready" in caplog.messages


def test_unknown_type_is_ignored(caplog) -> None:
    b = bridge.Bridge()
    with caplog.at_level(logging.INFO, logger="app.bridge"):
        b.handle({"type": "something-else"})
    assert "ui ready" not in caplog.messages


def test_index_html_csp_and_empty_state() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    csp = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    assert csp is not None
    assert csp.group(1) == (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:"
    )
    assert 'id="empty-state"' in html
    assert "Brak skonfigurowanych agentów" in html
    assert "Dodaj agenta" in html
    # Local resources only (FR-4).
    assert not re.search(r'(src|href)="(https?:)?//', html)
    for name in ("app.js", "style.css"):
        assert (UI_DIR / name).is_file()


# -- routing to the controller and dispatch (S3-T3) -------------------------------------------


class RecordingHandler:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def ready(self) -> None:
        self.calls.append(("ready",))

    def send(self, text, images=None) -> None:
        self.calls.append(("send", text, images))

    def cancel(self) -> None:
        self.calls.append(("cancel",))

    def new_chat(self) -> None:
        self.calls.append(("new_chat",))


class SinkBridge(bridge.Bridge):
    """Records dispatched events instead of running JavaScript."""

    def __init__(self, handler=None) -> None:
        super().__init__(handler=handler)
        self.dispatched: list[dict] = []

    def dispatch(self, event: dict) -> None:
        self.dispatched.append(event)


def test_messages_are_routed_to_the_handler() -> None:
    handler = RecordingHandler()
    b = SinkBridge(handler)
    for message in (
        {"type": "ready"},
        {"type": "send", "text": "hej"},
        {"type": "cancel"},
        {"type": "new_chat"},
    ):
        b.handle(message)
    assert handler.calls == [("ready",), ("send", "hej", None), ("cancel",), ("new_chat",)]
    assert b.dispatched == []


def test_message_without_type_is_ignored() -> None:
    handler = RecordingHandler()
    b = SinkBridge(handler)
    raw = json.dumps({"text": "hej"})

    class Value:  # stands in for the JSC value of postMessage
        def to_json(self, _indent):
            return raw

    b._on_script_message(None, Value())
    assert handler.calls == []
    assert b.dispatched == []


def test_send_with_images_is_passed_on() -> None:
    handler = RecordingHandler()
    b = SinkBridge(handler)
    images = [{"type": "image", "mimeType": "image/png", "data": "AAAA"}]
    b.handle({"type": "send", "text": "", "images": images})
    assert handler.calls == [("send", "", images)]


@pytest.mark.parametrize(
    "message",
    [
        {"type": "send"},
        {"type": "send", "text": 5},
        {"type": "send", "text": None},
        {"type": "send", "text": "a", "images": "x"},
        {"type": "send", "text": "a", "images": [{"type": "image"}]},
    ],
)
def test_invalid_send_is_answered_with_error(message, caplog) -> None:
    handler = RecordingHandler()
    b = SinkBridge(handler)
    with caplog.at_level(logging.WARNING, logger="app.bridge"):
        b.handle(message)
    assert handler.calls == []
    assert [e["type"] for e in b.dispatched] == ["error"]
    assert any("invalid 'send'" in m for m in caplog.messages)


def test_send_without_handler_is_answered_with_error() -> None:
    b = SinkBridge()
    b.handle({"type": "send", "text": "a"})
    assert [e["type"] for e in b.dispatched] == ["error"]


@pytest.mark.parametrize("kind", ["something-else", "permission"])
def test_unhandled_types_log_warning(kind, caplog) -> None:
    handler = RecordingHandler()
    b = SinkBridge(handler)
    with caplog.at_level(logging.WARNING, logger="app.bridge"):
        b.handle({"type": kind})
    assert handler.calls == []
    assert b.dispatched == []
    assert any(kind in m for m in caplog.messages)


@pytest.mark.parametrize(
    "text",
    ["</script><script>alert(1)</script>", "a\u2028b\u2029c", "<!-- & -->", "zażółć 🎉"],
)
def test_dispatch_script_is_safe(text) -> None:
    script = bridge.dispatch_script({"type": "text_delta", "text": text})
    assert script.startswith("window.aiPanel.dispatch(") and script.endswith(")")
    payload = script[len("window.aiPanel.dispatch(") : -1]
    assert payload.isascii()
    for bad in ("<", ">", "&", "\u2028", "\u2029"):
        assert bad not in payload
    assert json.loads(payload) == {"type": "text_delta", "text": text}


def test_dispatch_without_webview_is_dropped() -> None:
    bridge.Bridge().dispatch({"type": "done", "stop_reason": "end_turn"})


# -- debug dump (S3-T4) -------------------------------------------------------------------


def test_dump_is_forwarded_only_when_requested(caplog) -> None:
    b = SinkBridge(RecordingHandler())
    dumps: list[dict] = []
    b.on_dump = dumps.append
    with caplog.at_level(logging.WARNING, logger="app.bridge"):
        b.handle({"type": "dump", "state": {"screen": "chat"}})
    assert dumps == []
    assert any("unrequested" in m for m in caplog.messages)

    b.request_dump()
    assert b.dispatched == [{"type": "request_dump"}]
    b.handle({"type": "dump", "state": {"screen": "chat"}})
    b.handle({"type": "dump", "state": {"screen": "empty"}})  # one request, one answer
    assert dumps == [{"screen": "chat"}]


def test_dump_without_on_dump_is_dropped() -> None:
    b = SinkBridge(RecordingHandler())
    b.request_dump()
    b.handle({"type": "dump", "state": {}})  # no on_dump (AI_PANEL_DEBUG unset): nothing


@pytest.mark.parametrize("state", [None, "x", [], 1])
def test_invalid_dump_state_is_dropped(state) -> None:
    b = SinkBridge(RecordingHandler())
    dumps: list = []
    b.on_dump = dumps.append
    b.request_dump()
    b.handle({"type": "dump", "state": state})
    assert dumps == []


def test_pending_dump_requests_are_bounded() -> None:
    b = SinkBridge(RecordingHandler())
    dumps: list = []
    b.on_dump = dumps.append
    for _ in range(bridge.MAX_PENDING_DUMPS + 5):
        b.request_dump()
    for _ in range(bridge.MAX_PENDING_DUMPS + 5):
        b.handle({"type": "dump", "state": {}})
    assert len(dumps) == bridge.MAX_PENDING_DUMPS
