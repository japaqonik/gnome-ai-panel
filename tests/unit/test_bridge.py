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
