"""ChatController + real AcpBackend + fake agent: crash → restart, cancel with a running tool,
an agent that ignores ``session/cancel`` (S4-T3, FR-16, FR-17)."""

import asyncio

from app import backends, strings
from app.controller import ChatController
from tests.integration.test_controller_acp import ListSink, controller_for, gone, wait_for


def reply_text(events: list[dict]) -> str:
    return "".join(e["text"] for e in events if e["type"] == "text_delta")


async def turn(controller: ChatController, sink: ListSink, text: str) -> list[dict]:
    start = len(sink.events)
    controller.send(text)
    await wait_for(lambda: not controller.busy)
    return sink.events[start:]


async def test_crash_once_then_restart_and_next_turn(isolated_env, tmp_path) -> None:
    controller, sink = controller_for(tmp_path, "crash-once")
    try:
        first = await turn(controller, sink, "a")
        error = first[-1]
        assert error["type"] == "error"
        assert error["kind"] == "crashed"
        assert error["title"] == strings.CHAT_ERROR_TITLES["crashed"]
        assert "kod 3" in error["message"]
        assert "boom" not in error["message"]  # stderr is shown separately, collapsed
        assert error["stderr"] == "boom"
        assert error["hint"] == strings.CHAT_ERROR_HINTS["crashed"]
        crashed_pid = controller._backend.pid
        assert crashed_pid is None  # the process is gone

        second = await turn(controller, sink, "b")
        assert [e["type"] for e in second][:2] == ["turn_start", "notice"]
        assert second[1]["text"] == strings.CTRL_AGENT_RESTARTED
        assert reply_text(second) == "Echo: b"
        assert second[-1] == {"type": "done", "stop_reason": "end_turn"}
        assert controller._backend.pid is not None

        third = await turn(controller, sink, "c")
        assert "notice" not in [e["type"] for e in third]
        assert reply_text(third) == "Echo: c"
    finally:
        await controller.close()
        await backends.close_all()


async def test_restart_limit_blocks_until_new_chat(isolated_env, tmp_path) -> None:
    controller, sink = controller_for(tmp_path, "crash")
    try:
        # First start + RESTART_LIMIT restarts crash; the next restart is refused.
        for _ in range(1 + backends.acp.RESTART_LIMIT):
            events = await turn(controller, sink, "x")
            assert events[-1]["kind"] == "crashed" and not events[-1]["blocked"]
        events = await turn(controller, sink, "x")
        assert events[-1]["blocked"] is True
        assert "zbyt często" in events[-1]["message"]
        assert controller.blocked
        events = await turn(controller, sink, "x")
        assert [e["type"] for e in events] == ["error"]
        assert events[0]["message"] == strings.CTRL_BLOCKED
        controller.new_chat()
        assert not controller.blocked
    finally:
        await controller.close()
        await backends.close_all()


async def test_cancel_with_in_progress_tool_marks_card_cancelled(isolated_env, tmp_path) -> None:
    controller, sink = controller_for(tmp_path, "slow-tool")
    try:
        controller.send("długo")
        await wait_for(lambda: "text_delta" in sink.types())
        call = next(e for e in sink.events if e["type"] == "tool_call")
        assert call["status"] == "in_progress"
        controller.cancel()
        # Marked at once, before the agent answers.
        assert sink.events[-1] == {"type": "tool_update", "id": "call_long", "status": "cancelled"}
        await wait_for(lambda: not controller.busy, timeout=3)
        assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
        assert controller.messages[-1]["tools"][0]["status"] == "cancelled"
        assert controller.messages[-1]["stop_reason"] == "cancelled"
    finally:
        await controller.close()
        await backends.close_all()


async def test_agent_ignoring_cancel_ends_turn_after_timeout(isolated_env, tmp_path) -> None:
    controller, sink = controller_for(tmp_path, "stubborn")
    controller._cancel_timeout_s = 0.5
    pid = None
    try:
        controller.send("długo")
        await wait_for(lambda: "text_delta" in sink.types())
        pid = controller._backend.pid
        controller.cancel()
        await asyncio.sleep(0.25)
        assert controller.busy  # the agent keeps going; the controller still waits
        await wait_for(lambda: not controller.busy, timeout=3)
        assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
        count = len(sink.events)
        await asyncio.sleep(0.5)
        assert len(sink.events) == count  # later chunks of the abandoned turn are dropped

        # The next prompt gets a new session in the same process.
        controller.send("znowu")
        await wait_for(lambda: "notice" in sink.types())
        notice = next(e for e in sink.events if e["type"] == "notice")
        assert notice["text"] == strings.CTRL_SESSION_ABANDONED
        assert controller._backend.pid == pid
        controller.new_chat()
    finally:
        await controller.close()
        await backends.close_all()
    assert pid is not None
    await wait_for(lambda: gone(pid), timeout=5)
