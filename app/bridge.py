"""JS -> Python bridge: ``window.webkit.messageHandlers.bridge.postMessage(obj)``.

Messages are JSON objects with a string ``type`` (PLAN §12.2). Anything else coming from
the web view is logged and dropped: the page renders model output, so it is not trusted.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("WebKit", "6.0")
from gi.repository import WebKit  # noqa: E402

log = logging.getLogger(__name__)

HANDLER_NAME = "bridge"
# Upper bound for one message; larger payloads are dropped (images arrive in later stages).
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

Message = dict[str, Any]


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


class Bridge:
    """Receives messages from the page and routes them by ``type``."""

    def __init__(self, on_ready: Callable[[], None] | None = None) -> None:
        self._on_ready = on_ready
        self._manager: WebKit.UserContentManager | None = None

    def attach(self, manager: WebKit.UserContentManager) -> None:
        """Register the ``bridge`` script message handler on ``manager``."""
        manager.connect(f"script-message-received::{HANDLER_NAME}", self._on_script_message)
        if not manager.register_script_message_handler(HANDLER_NAME, None):
            raise RuntimeError(f"cannot register script message handler {HANDLER_NAME!r}")
        self._manager = manager

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
        if kind == "ready":
            log.info("ui ready")
            if self._on_ready is not None:
                self._on_ready()
        else:
            log.debug("bridge: unhandled message type %r", kind)
