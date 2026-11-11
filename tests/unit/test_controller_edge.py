"""Extra ChatController edge cases added by the tester (S3-T3): the UI contract (one
``done``/``error`` per ``send``, nothing after it, idempotent ``cancel``) on less common
interleavings of cancel, new_chat, close and session creation."""

import asyncio
import logging

from app import strings
from app.backends.base import Done, Error, TextDelta
from tests.unit.test_controller import FakeBackend, make, settle

TERMINAL = ("done", "error")


def assert_contract(events: list[dict], sends: int) -> None:
    """``sends`` sends gave exactly ``sends`` terminal events and no turn event follows a
    terminal one before the next ``turn_start``."""
    assert sum(e["type"] in TERMINAL for e in events) == sends, events
    open_turn = False
    for event in events:
        kind = event["type"]
        if kind == "turn_start":
            assert not open_turn, events
            open_turn = True
        elif kind in TERMINAL:
            open_turn = False
        elif kind == "text_delta":
            assert open_turn, f"text_delta outside a turn: {events}"


async def test_text_after_done_in_stream_is_not_dispatched() -> None:
    controller, sink, backend, _ = make([TextDelta("a"), Done("end_turn"), TextDelta("late")])
    controller.send("x")
    await settle(controller)
    assert sink.types() == ["turn_start", "text_delta", "done"]
    assert backend.closed_iterators == 1
    assert_contract(sink.events, 1)


async def test_text_after_error_in_stream_is_not_dispatched() -> None:
    controller, sink, _, _ = make([Error("bad", "protocol"), TextDelta("late"), Done("end_turn")])
    controller.send("x")
    await settle(controller)
    assert sink.types() == ["turn_start", "error"]


async def test_send_after_cancel_but_before_done_is_rejected() -> None:
    controller, sink, backend, _ = make(["wait"])
    gate = asyncio.Event()
    original = backend.cancel

    async def slow_cancel(session_id):
        await gate.wait()
        await original(session_id)

    backend.cancel = slow_cancel
    controller.send("first")
    await asyncio.sleep(0.02)
    controller.cancel()
    controller.send("second")  # the agent has not confirmed the cancel yet
    assert sink.events[-1] == {
        "type": "error",
        "message": strings.CTRL_TURN_RUNNING,
        "kind": "other",
    }
    gate.set()
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    # The rejection ``error`` sits inside the running turn (the page never sends while busy,
    # so only the count is checked here, not the ordering).
    assert sum(e["type"] in TERMINAL for e in sink.events) == 2
    assert sink.types().count("done") == 1
    assert len(backend.prompts) == 1


async def test_send_right_after_cancel_during_session_creation_reuses_pending_session() -> None:
    controller, sink, backend, _ = make([Done("end_turn")])
    backend.session_gate = asyncio.Event()
    controller.send("a")
    await asyncio.sleep(0.02)
    controller.cancel()
    controller.cancel()
    controller.send("b")  # session still being created
    await asyncio.sleep(0.02)
    backend.session_gate.set()
    await settle(controller)
    assert backend.sessions == ["s1"]
    assert backend.prompts == [("s1", [{"type": "text", "text": "b"}])]
    assert backend.cancels == []  # nothing was prompted when cancel came
    assert_contract(sink.events, 2)
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}


async def test_new_chat_during_session_creation_does_not_adopt_old_session() -> None:
    controller, sink, backend, _ = make([Done("end_turn")])
    backend.session_gate = asyncio.Event()
    controller.send("a")
    await asyncio.sleep(0.02)
    controller.new_chat()
    backend.session_gate.set()
    await settle(controller)
    assert backend.sessions == ["s1"]
    assert controller.session_id is None  # s1 belonged to the old conversation
    controller.send("b")
    await settle(controller)
    assert backend.sessions == ["s1", "s2"]
    assert backend.prompts == [("s2", [{"type": "text", "text": "b"}])]
    assert_contract([e for e in sink.events if e["type"] != "conversation"], 2)


async def test_repeated_new_chat_during_turn_gives_one_done() -> None:
    controller, sink, backend, _ = make([TextDelta("a"), "wait"])
    controller.send("x")
    await asyncio.sleep(0.02)
    controller.new_chat()
    controller.new_chat()
    controller.cancel()  # no turn any more
    await settle(controller)
    assert sink.types().count("done") == 1
    assert sink.types().count("conversation") == 2
    assert backend.cancels == []


async def test_cancel_and_events_after_close_do_nothing() -> None:
    controller, sink, backend, _ = make(["wait"])
    controller.send("x")
    await asyncio.sleep(0.02)
    await controller.close()
    count = len(sink.events)
    controller.cancel()
    await asyncio.sleep(0.02)
    assert len(sink.events) == count
    assert sink.types().count("done") == 1


async def test_failing_backend_cancel_is_logged_and_turn_still_ends(caplog) -> None:
    controller, sink, backend, _ = make(["wait"])

    async def broken_cancel(session_id):
        backend._cancelled.set()  # the agent stops anyway
        raise RuntimeError("pipe closed")

    backend.cancel = broken_cancel
    controller.send("x")
    await asyncio.sleep(0.02)
    with caplog.at_level(logging.WARNING, logger="app.controller"):
        controller.cancel()
        controller.cancel()
        await settle(controller)
    assert "cancel failed" in caplog.text
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    assert_contract(sink.events, 1)


async def test_mixed_sequence_keeps_contract() -> None:
    backend = FakeBackend([TextDelta("a"), TextDelta("b"), Done("end_turn")])
    controller, sink, _, _ = make(backend=backend)
    sends = 0
    for text in ["1", "", "2"]:
        controller.send(text)
        sends += 1
        controller.send("while busy")
        sends += 1
        controller.cancel()
        controller.cancel()
        await settle(controller)
    backend.script = ["wait"]
    controller.send("3")
    sends += 1
    await asyncio.sleep(0.02)
    for _ in range(5):
        controller.cancel()
    await settle(controller)
    assert_contract(sink.events, sends)
    assert backend.cancels == ["s1"]
