"""JS ⇄ Python bridge (PLAN §12.2).

JS → Python: ``window.webkit.messageHandlers.bridge.postMessage(obj)``. Messages are JSON
objects with a string ``type``; their fields are checked here before they reach the
controller. Anything else coming from the web view is logged and dropped: the page renders
model output, so it is not trusted.

Python → JS: ``Bridge.dispatch(obj)`` runs ``window.aiPanel.dispatch(<json>)`` in the page.
"""

import json
import logging
from collections.abc import Callable
from typing import Any, Protocol

import gi

gi.require_version("WebKit", "6.0")
from gi.repository import WebKit  # noqa: E402

from app import strings  # noqa: E402

log = logging.getLogger(__name__)

HANDLER_NAME = "bridge"
# Upper bound for one message; larger payloads are dropped (images arrive in later stages).
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

MAX_PENDING_DUMPS = 4

Message = dict[str, Any]

# Messages of later stages (PLAN §12.2): known, but not handled yet.
LATER_TYPES = frozenset(
    {
        "permission",
        "select_agent",
        "set_option",
        "open_link",
        "pin",
        "escape",
        "history_list",
        "history_open",
        "history_delete",
        "open_settings",
        "secret_prompt_reply",
    }
)


class MessageHandler(Protocol):
    """What the bridge routes messages to (``controller.ChatController``)."""

    def ready(self) -> None: ...
    def send(self, text: str, images: list[dict[str, Any]] | None = None) -> None: ...
    def cancel(self) -> None: ...
    def new_chat(self) -> None: ...


def parse_message(raw: str | None) -> Message | None:
    """Decode one bridge message. Returns ``None`` when it is not a valid message."""
    if raw is None:
        return None
    if len(raw) > MAX_MESSAGE_BYTES:
        log.warning("bridge: message of %d bytes dropped (too large)", len(raw))
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("bridge: message is not valid JSON, dropped")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("type"), str) or not data["type"]:
        log.warning("bridge: message without a string 'type', dropped")
        return None
    return data


def _valid_images(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(part, dict)
        and part.get("type") == "image"
        and isinstance(part.get("mimeType"), str)
        and isinstance(part.get("data"), str)
        for part in value
    )


def dispatch_script(obj: Message) -> str:
    """JavaScript that hands ``obj`` to the page.

    ``json.dumps`` with ``ensure_ascii`` escapes U+2028/U+2029 (line terminators in older
    JavaScript); ``<``, ``>`` and ``&`` are escaped too so the text never contains markup
    such as ``</script>``.
    """
    payload = (
        json.dumps(obj, ensure_ascii=True, allow_nan=False, default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return "window.aiPanel.dispatch(" + payload + ")"


class Bridge:
    """Receives messages from the page, routes them by ``type`` and dispatches events back.

    Implements ``controller.UiSink``.
    """

    def __init__(
        self,
        on_ready: Callable[[], None] | None = None,
        handler: MessageHandler | None = None,
    ) -> None:
        self._on_ready = on_ready
        self.handler = handler
        # Debug only (``debug-dump``): receives the ``state`` of a requested ``dump`` message.
        self.on_dump: Callable[[Message], None] | None = None
        self._dumps_requested = 0
        self._manager: WebKit.UserContentManager | None = None
        self._webview: WebKit.WebView | None = None

    def attach(self, webview: WebKit.WebView) -> None:
        """Register the ``bridge`` script message handler of ``webview``'s page."""
        manager = webview.get_user_content_manager()
        manager.connect(f"script-message-received::{HANDLER_NAME}", self._on_script_message)
        if not manager.register_script_message_handler(HANDLER_NAME, None):
            raise RuntimeError(f"cannot register script message handler {HANDLER_NAME!r}")
        self._manager = manager
        self._webview = webview

    # -- JS → Python -----------------------------------------------------------------------

    def _on_script_message(self, _manager: WebKit.UserContentManager, value: Any) -> None:
        try:
            raw = value.to_json(0)
        except Exception:  # JSC raises for values that have no JSON form (functions, cycles)
            log.warning("bridge: message cannot be converted to JSON, dropped")
            return
        message = parse_message(raw)
        if message is not None:
            self.handle(message)

    def handle(self, message: Message) -> None:
        kind = message["type"]
        handler = self.handler
        if kind == "ready":
            log.info("ui ready")
            if self._on_ready is not None:
                self._on_ready()
            if handler is not None:
                handler.ready()
        elif kind == "send":
            self._handle_send(message)
        elif kind == "cancel":
            if handler is not None:
                handler.cancel()
        elif kind == "new_chat":
            if handler is not None:
                handler.new_chat()
        elif kind == "dump":
            self._handle_dump(message)
        elif kind in LATER_TYPES:
            log.warning("bridge: message type %r is not supported yet, dropped", kind)
        else:
            log.warning("bridge: unknown message type %r, dropped", kind[:64])

    def _handle_send(self, message: Message) -> None:
        text = message.get("text")
        images = message.get("images")
        if not isinstance(text, str) or (images is not None and not _valid_images(images)):
            log.warning("bridge: invalid 'send' message, rejected")
            # The page waits for the end of the turn it just started: always answer.
            self.dispatch(
                {"type": "error", "message": strings.CTRL_INVALID_MESSAGE, "kind": "other"}
            )
            return
        if self.handler is None:
            self.dispatch({"type": "error", "message": strings.CTRL_NO_AGENT, "kind": "other"})
            return
        self.handler.send(text, images)

    def _handle_dump(self, message: Message) -> None:
        # The page is not trusted: only answers to our own requests are written.
        if self.on_dump is None or self._dumps_requested == 0:
            log.warning("bridge: unrequested 'dump' message, dropped")
            return
        self._dumps_requested -= 1
        state = message.get("state")
        if not isinstance(state, dict):
            log.warning("bridge: invalid 'dump' message, dropped")
            return
        self.on_dump(state)

    # -- Python → JS -----------------------------------------------------------------------

    def request_dump(self) -> None:
        """Ask the page for its state; the answer goes to ``on_dump``."""
        # Bounded: a page that never answers must not make later dumps unconditional.
        self._dumps_requested = min(self._dumps_requested + 1, MAX_PENDING_DUMPS)
        self.dispatch({"type": "request_dump"})

    def run_script(self, script: str, name: str = "script") -> None:
        """Evaluate ``script`` (built by the app, never from page data) in the page."""
        webview = self._webview
        if webview is None:
            log.debug("bridge: no web view, %s dropped", name)
            return
        webview.evaluate_javascript(script, -1, None, None, None, self._on_evaluated, None)

    def dispatch(self, event: Message) -> None:
        """Hand ``event`` to ``window.aiPanel.dispatch`` in the page."""
        webview = self._webview
        if webview is None:
            log.debug("bridge: no web view, %s dropped", event.get("type"))
            return
        try:
            script = dispatch_script(event)
        except (TypeError, ValueError) as exc:
            log.error("bridge: %s cannot be encoded: %s", event.get("type"), exc)
            return
        webview.evaluate_javascript(script, -1, None, None, None, self._on_evaluated, None)

    @staticmethod
    def _on_evaluated(webview: WebKit.WebView, result: Any, _data: Any) -> None:
        try:
            webview.evaluate_javascript_finish(result)
        except Exception as exc:  # GLib.Error: page not loaded yet, exception in the page
            log.warning("bridge: dispatch failed: %s", getattr(exc, "message", exc))
