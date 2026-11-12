"""ChatController edge cases of cancel, the cancel watchdog and error texts (S4-T3, tester)."""

import asyncio

from app import strings
from app.backends.base import Done, Error, TextDelta, ToolCall
from app.controller import error_event
from tests.unit.test_controller import FakeBackend, make, settle
from tests.unit.test_controller_failures import StubbornBackend, tool_updates


async def test_repeated_cancel_marks_tools_once_and_cancels_once() -> None:
    backend = StubbornBackend([ToolCall("t1", title="T", status="in_progress"), "wait"])
    controller, sink, _, _ = make(backend=backend, cancel_timeout_s=0.1)
    controller.send("x")
    await asyncio.sleep(0.05)
    controller.cancel()
    controller.cancel()
    controller.cancel()
    await settle(controller)
    assert tool_updates(sink) == [{"type": "tool_update", "id": "t1", "status": "cancelled"}]
    assert backend.cancels == ["s1"]
    assert sink.types().count("done") == 1
    assert not controller._tasks


async def test_new_chat_while_waiting_for_a_stubborn_cancel() -> None:
    # The watchdog of the old turn must not leak into the new conversation.
    backend = StubbornBackend([TextDelta("a"), "wait"])
    controller, sink, _, _ = make(backend=backend, cancel_timeout_s=0.1)
    controller.send("x")
    await asyncio.sleep(0.05)
    controller.cancel()
    controller.new_chat()
    await asyncio.sleep(0.2)
    await settle(controller)
    after_conversation = sink.types()[sink.types().index("conversation") + 1 :]
    assert after_conversation == []  # nothing of the old turn after the new conversation
    assert sink.types().count("done") <= 1

    backend.script = [TextDelta("ok"), Done("end_turn")]
    controller.send("y")
    await settle(controller)
    assert "notice" not in sink.types()
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}


async def test_cancel_while_session_is_created_needs_no_watchdog() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.session_gate = asyncio.Event()
    controller, sink, _, _ = make(backend=backend, cancel_timeout_s=0.05)
    controller.send("x")
    await asyncio.sleep(0.02)
    controller.cancel()
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    assert backend.cancels == []
    backend.session_gate.set()
    await settle(controller)
    await asyncio.sleep(0.1)
    assert sink.types().count("done") == 1
    assert "notice" not in sink.types()


def test_crashed_stderr_not_in_message_keeps_the_message() -> None:
    event = error_event(Error("Proces zakończył się (kod 1).", "crashed", stderr="ślad"))
    assert event["message"] == "Proces zakończył się (kod 1)."
    assert event["stderr"] == "ślad"
    assert event["stderr_label"] == strings.CHAT_STDERR_LABEL


def test_empty_stderr_is_not_shown() -> None:
    event = error_event(Error("x", "crashed", stderr=""))
    assert event["stderr"] is None
    assert event["stderr_label"] is None


def test_auth_methods_with_bad_entries_are_skipped_and_capped() -> None:
    methods = [{"id": "a"}, {"name": 5}, "str", None, {"name": "B", "description": "  "}]
    methods += [{"id": f"m{i}"} for i in range(50)]
    event = error_event(Error("raw", "auth", auth_methods=methods))
    assert event["auth_methods"][:2] == ["a", "B"]
    assert len(event["auth_methods"]) == 20
    assert event["message"] == strings.CHAT_AUTH_MESSAGE


def test_blocked_error_uses_the_restart_limit_hint() -> None:
    event = error_event(Error("x", "spawn"), blocked=True)
    assert event["blocked"] is True
    assert event["hint"] == strings.CHAT_RESTART_LIMIT_HINT
