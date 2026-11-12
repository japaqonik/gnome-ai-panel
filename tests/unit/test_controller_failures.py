"""ChatController: cancel, readable errors, restart notice and restart limit (S4-T3)."""

import asyncio

import pytest

from app import strings
from app.backends.base import (
    ERROR_KINDS,
    BackendError,
    Done,
    Error,
    RestartLimitError,
    TextDelta,
    ToolCall,
    ToolUpdate,
)
from app.controller import error_event
from tests.unit.test_controller import FakeBackend, make, settle

ERROR_KEYS = {
    "type",
    "kind",
    "title",
    "message",
    "hint",
    "stderr",
    "stderr_label",
    "auth_methods",
    "methods_label",
    "blocked",
}


def tool(tool_id: str, status: str) -> ToolCall:
    return ToolCall(tool_id, title=f"Narzędzie {tool_id}", status=status)


def tool_updates(sink) -> list[dict]:
    return [e for e in sink.events if e["type"] == "tool_update"]


# -- error texts ----------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ERROR_KINDS)
async def test_every_error_kind_gets_title_and_hint(kind) -> None:
    controller, sink, _, _ = make([TextDelta("a"), Error("Coś poszło źle", kind)])
    controller.send("x")
    await settle(controller)
    event = sink.events[-1]
    assert set(event) == ERROR_KEYS
    assert event["type"] == "error"
    assert event["kind"] == kind
    assert event["title"] == strings.CHAT_ERROR_TITLES[kind]
    assert event["hint"] == strings.CHAT_ERROR_HINTS.get(kind)
    assert event["blocked"] is False
    if kind == "auth":
        assert event["message"] == strings.CHAT_AUTH_MESSAGE
    else:
        assert event["message"] == "Coś poszło źle"
    # The stored reply records the message shown.
    assert controller.messages[-1]["error"] == {"message": event["message"], "kind": kind}


def test_every_kind_has_a_title_and_specific_kinds_have_hints() -> None:
    assert set(strings.CHAT_ERROR_TITLES) == set(ERROR_KINDS)
    for kind in ("spawn", "timeout", "protocol", "auth", "crashed"):
        assert strings.CHAT_ERROR_HINTS[kind]
    assert "zaloguj się w terminalu" in strings.CHAT_ERROR_HINTS["auth"].lower()
    assert "logowania swojego agenta" in strings.CHAT_ERROR_HINTS["auth"]


def test_unknown_kind_is_shown_as_other() -> None:
    event = error_event(Error("x", "weird"))  # type: ignore[arg-type]
    assert event["kind"] == "other"
    assert event["title"] == strings.CHAT_ERROR_TITLES["other"]
    assert event["hint"] is None


def test_crashed_moves_stderr_out_of_the_message() -> None:
    tail = "line 1\nboom"
    message = "Proces agenta zakończył działanie (kod 3).\n" + strings.ACP_STDERR_TAIL.format(
        stderr=tail
    )
    event = error_event(Error(message, "crashed", stderr=tail))
    assert event["message"] == "Proces agenta zakończył działanie (kod 3)."
    assert event["stderr"] == tail
    assert event["stderr_label"] == strings.CHAT_STDERR_LABEL
    assert event["hint"] == strings.CHAT_ERROR_HINTS["crashed"]


def test_crashed_without_stderr() -> None:
    event = error_event(Error("Proces agenta zakończył działanie (kod 1).", "crashed"))
    assert event["stderr"] is None
    assert event["stderr_label"] is None
    assert event["message"] == "Proces agenta zakończył działanie (kod 1)."


def test_auth_lists_the_agents_methods() -> None:
    methods = [
        {"id": "login", "name": "Fake login", "description": "Run `fake-agent login`"},
        {"id": "token"},
        {"name": 5},
        "junk",
    ]
    event = error_event(Error("raw", "auth", auth_methods=methods))
    assert event["message"] == strings.CHAT_AUTH_MESSAGE
    assert event["auth_methods"] == ["Fake login: Run `fake-agent login`", "token"]
    assert event["methods_label"] == strings.CHAT_AUTH_METHODS
    assert event["hint"] == strings.CHAT_ERROR_HINTS["auth"]


def test_auth_without_methods() -> None:
    event = error_event(Error("raw", "auth"))
    assert event["auth_methods"] == []
    assert event["methods_label"] == strings.CHAT_AUTH_NO_METHODS


async def test_session_error_kind_spawn_reaches_the_ui() -> None:
    backend = FakeBackend(session_error=Error("Nie znaleziono polecenia: agent", "spawn"))
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    assert sink.types() == ["turn_start", "error"]
    assert sink.events[-1]["title"] == strings.CHAT_ERROR_TITLES["spawn"]
    assert sink.events[-1]["message"] == "Nie znaleziono polecenia: agent"


# -- restart after a crash ------------------------------------------------------------------


async def test_crash_then_next_prompt_gets_new_session_and_notice() -> None:
    backend = FakeBackend([TextDelta("a"), Error("boom", "crashed", stderr="boom")])
    controller, sink, _, _ = make(backend=backend)
    controller.send("pierwszy")
    await settle(controller)
    assert sink.events[-1]["kind"] == "crashed"
    assert "notice" not in sink.types()

    backend.script = [TextDelta("Echo: b"), Done("end_turn")]
    start = len(sink.events)
    controller.send("b")
    await settle(controller)
    assert sink.events[start:] == [
        {"type": "turn_start"},
        {"type": "notice", "kind": "context_lost", "text": strings.CTRL_AGENT_RESTARTED},
        {"type": "text_delta", "text": "Echo: b"},
        {"type": "done", "stop_reason": "end_turn"},
    ]
    assert backend.sessions == ["s1", "s2"]
    assert [p[0] for p in backend.prompts] == ["s1", "s2"]

    # Only once: the next turn uses the new session without a notice.
    controller.send("c")
    await settle(controller)
    assert sink.types().count("notice") == 1
    assert backend.sessions == ["s1", "s2"]


def test_restart_notice_text() -> None:
    assert strings.CTRL_AGENT_RESTARTED == (
        "Agent został uruchomiony ponownie, poprzedni kontekst utracony"
    )


async def test_failed_first_start_gives_no_notice() -> None:
    # The agent died while starting: there was no session (and no context) to lose.
    backend = FakeBackend([Done("end_turn")], session_error=Error("exit", "crashed"))
    controller, sink, _, _ = make(backend=backend)
    controller.send("a")
    await settle(controller)
    backend.session_error = None
    controller.send("b")
    await settle(controller)
    assert "notice" not in sink.types()
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}


async def test_new_chat_drops_a_pending_notice() -> None:
    backend = FakeBackend([Error("boom", "crashed")])
    controller, sink, _, _ = make(backend=backend)
    controller.send("a")
    await settle(controller)
    controller.new_chat()
    backend.script = [Done("end_turn")]
    controller.send("b")
    await settle(controller)
    assert "notice" not in sink.types()


# -- restart limit --------------------------------------------------------------------------


class LimitBackend(FakeBackend):
    def __init__(self, script=None) -> None:
        super().__init__(script)
        self.limit_hit = False

    async def new_session(self) -> str:
        if self.limit_hit:
            raise RestartLimitError(
                Error(strings.ACP_RESTART_LIMIT.format(count=3, window=60), "crashed")
            )
        return await super().new_session()


async def test_restart_limit_blocks_until_new_chat() -> None:
    backend = LimitBackend([Error("boom", "crashed")])
    controller, sink, _, _ = make(backend=backend)
    controller.send("a")
    await settle(controller)
    backend.limit_hit = True
    controller.send("b")
    await settle(controller)
    event = sink.events[-1]
    assert event["type"] == "error"
    assert event["kind"] == "crashed"
    assert event["blocked"] is True
    assert event["hint"] == strings.CHAT_RESTART_LIMIT_HINT
    assert "zbyt często" in event["message"]
    assert controller.blocked

    # Blocked: answered with an error at once, nothing reaches the backend.
    prompts, count = len(backend.prompts), len(sink.events)
    controller.send("c")
    assert sink.events[count:] == [
        error_event(Error(strings.CTRL_BLOCKED, "crashed"), blocked=True)
    ]
    assert not controller.busy
    await settle(controller)
    assert len(backend.prompts) == prompts

    controller.new_chat()
    assert not controller.blocked
    backend.limit_hit = False
    backend.script = [TextDelta("ok"), Done("end_turn")]
    controller.send("d")
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}


async def test_restart_limit_error_is_a_backend_error() -> None:
    assert issubclass(RestartLimitError, BackendError)


# -- cancel ---------------------------------------------------------------------------------


async def test_cancel_marks_unfinished_tools_cancelled_at_once() -> None:
    controller, sink, backend, _ = make(
        [tool("t1", "in_progress"), tool("t2", "pending"), tool("t3", "completed"), "wait"]
    )
    controller.send("x")
    await asyncio.sleep(0.05)
    assert controller.busy
    controller.cancel()
    # Before the backend confirms anything.
    assert tool_updates(sink) == [
        {"type": "tool_update", "id": "t1", "status": "cancelled"},
        {"type": "tool_update", "id": "t2", "status": "cancelled"},
    ]
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    assert len(tool_updates(sink)) == 2  # not repeated at the end of the turn
    statuses = {t["id"]: t["status"] for t in controller.messages[-1]["tools"]}
    assert statuses == {"t1": "cancelled", "t2": "cancelled", "t3": "completed"}
    assert backend.cancels == ["s1"]


async def test_done_cancelled_marks_tools_cancelled() -> None:
    # The agent ended the turn as cancelled on its own (e.g. a cancel from elsewhere).
    controller, sink, _, _ = make(
        [tool("t1", "pending"), ToolUpdate("t1", status="in_progress"), Done("cancelled")]
    )
    controller.send("x")
    await settle(controller)
    assert sink.events[-2:] == [
        {"type": "tool_update", "id": "t1", "status": "cancelled"},
        {"type": "done", "stop_reason": "cancelled"},
    ]
    assert controller.messages[-1]["tools"][0]["status"] == "cancelled"


async def test_end_turn_keeps_tool_statuses() -> None:
    controller, sink, _, _ = make([tool("t1", "in_progress"), Done("end_turn")])
    controller.send("x")
    await settle(controller)
    assert tool_updates(sink) == []
    assert controller.messages[-1]["tools"][0]["status"] == "in_progress"


class StubbornBackend(FakeBackend):
    """Ignores cancel(): the turn would never end on its own."""

    async def cancel(self, session_id) -> None:
        self.cancels.append(session_id)


async def test_agent_ignoring_cancel_is_given_up_after_timeout() -> None:
    backend = StubbornBackend([TextDelta("a"), "wait"])
    controller, sink, _, _ = make(backend=backend, cancel_timeout_s=0.1)
    controller.send("x")
    await asyncio.sleep(0.05)
    controller.cancel()
    await asyncio.sleep(0.03)
    assert controller.busy  # still waiting for the agent
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    assert sink.types().count("done") == 1
    assert backend.closed_iterators == 1
    assert backend.cancels == ["s1"]
    assert controller.session_id is None

    # The next prompt does not go to the session the agent may still be busy with.
    backend.script = [TextDelta("ok"), Done("end_turn")]
    start = len(sink.events)
    controller.send("y")
    await settle(controller)
    assert sink.events[start:] == [
        {"type": "turn_start"},
        {"type": "notice", "kind": "context_lost", "text": strings.CTRL_SESSION_ABANDONED},
        {"type": "text_delta", "text": "ok"},
        {"type": "done", "stop_reason": "end_turn"},
    ]
    assert backend.sessions == ["s1", "s2"]


async def test_cancel_confirmed_in_time_keeps_the_session() -> None:
    controller, sink, backend, _ = make(["wait"], cancel_timeout_s=0.2)
    controller.send("x")
    await asyncio.sleep(0.02)
    controller.cancel()
    await settle(controller)
    assert not controller._tasks  # the watchdog stopped with the turn
    await asyncio.sleep(0.3)
    assert sink.types().count("done") == 1
    assert controller.session_id == "s1"
    backend.script = [Done("end_turn")]
    controller.send("y")
    await settle(controller)
    assert "notice" not in sink.types()
    assert backend.sessions == ["s1"]
