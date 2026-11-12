"""ChatController with a scripted FakeBackend and a list as the UiSink (S3-T3)."""

import asyncio
from pathlib import Path

import pytest

from app import strings
from app.backends.base import (
    BackendError,
    Done,
    Error,
    PermissionOption,
    PermissionRequest,
    TextDelta,
    ThinkingDelta,
)
from app.config import AcpAgent, ApiAgent, Config, ConfigError
from app.controller import (
    ChatController,
    choose_agent,
    default_agent_override,
    resolve_theme,
)


class ListSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def dispatch(self, event: dict) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


class FakeBackend:
    """``script`` is a list of events (or ``"wait"``: block until ``cancel()``)."""

    name = "fake"

    def __init__(self, script=None, *, session_error: Error | None = None) -> None:
        self.script = list(script or [])
        self.session_error = session_error
        self.sessions: list[str] = []
        self.prompts: list[tuple[str, list]] = []
        self.cancels: list[str] = []
        self.permissions: list[tuple[str, str | None]] = []
        self.closed_iterators = 0
        self.session_gate: asyncio.Event | None = None
        self._cancelled = asyncio.Event()
        # ACP configOptions reported for every session; set_option changes currentValue.
        self.options: list[dict] = []
        self.option_calls: list[tuple[str, str, str]] = []
        self.option_error: Error | None = None

    async def new_session(self) -> str:
        if self.session_gate is not None:
            await self.session_gate.wait()
        if self.session_error is not None:
            raise BackendError(self.session_error)
        session_id = f"s{len(self.sessions) + 1}"
        self.sessions.append(session_id)
        return session_id

    async def send(self, session_id, prompt):
        self.prompts.append((session_id, prompt))
        self._cancelled.clear()
        try:
            for item in self.script:
                if item == "wait":
                    await self._cancelled.wait()
                    yield TextDelta("late chunk")
                    yield Done("cancelled")
                    return
                await asyncio.sleep(0)
                yield item
        finally:
            self.closed_iterators += 1

    def respond_permission(self, request_id, option_id) -> None:
        self.permissions.append((request_id, option_id))

    async def cancel(self, session_id) -> None:
        self.cancels.append(session_id)
        self._cancelled.set()

    def config_options(self, session_id) -> list:
        return [dict(o) for o in self.options]

    async def set_option(self, session_id, config_id, value):
        self.option_calls.append((session_id, config_id, value))
        if self.option_error is not None:
            raise BackendError(self.option_error)
        for option in self.options:
            if option["id"] == config_id:
                option["currentValue"] = value
        return [dict(o) for o in self.options]

    async def close(self) -> None:
        pass


def acp(agent_id: str) -> AcpAgent:
    return AcpAgent(
        id=agent_id, name=agent_id.title(), command="agent", cwd=Path("/nonexistent/cwd")
    )


def make_config(*ids: str, default: str | None = None, errors=None) -> Config:
    return Config(
        path=Path("/nonexistent/config.toml"),
        agents={i: acp(i) for i in ids},
        default_agent=default,
        errors=list(errors or []),
    )


def make(script=None, *, config=None, backend=None, **kwargs):
    sink = ListSink()
    backend = backend or FakeBackend(script)
    created: list = []

    def factory(agent):
        created.append(agent.id)
        return backend

    controller = ChatController(config or make_config("echo"), sink, factory, **kwargs)
    return controller, sink, backend, created


async def settle(controller: ChatController, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while controller.busy or any(not t.done() for t in controller._tasks):
            await asyncio.sleep(0.005)


# -- agent selection and init ---------------------------------------------------------------


def test_choose_agent_order() -> None:
    config = make_config("a", "b", default="b")
    assert choose_agent(config) == "b"
    assert choose_agent(config, "a") == "a"
    assert choose_agent(config, "missing") == "b"
    assert choose_agent(make_config("a", "b")) == "a"
    assert choose_agent(make_config()) is None


def test_default_agent_override_env() -> None:
    assert default_agent_override({"AI_PANEL_DEFAULT_AGENT": "x"}) == "x"
    assert default_agent_override({"AI_PANEL_DEFAULT_AGENT": ""}) is None
    assert default_agent_override({}) is None


def test_no_agents_init_has_empty_list() -> None:
    controller, sink, _, _ = make(config=make_config())
    controller.ready()
    (init,) = sink.events
    assert init["type"] == "init"
    assert init["agents"] == []
    assert init["current"] is None


def test_init_lists_agents_and_config_errors() -> None:
    config = make_config(
        "a", "b", default="b", errors=[ConfigError("agents.x.command", "wymagane")]
    )
    config.chat.theme = "dark"
    controller, sink, _, _ = make(config=config)
    controller.ready()
    init = sink.events[0]
    assert init["agents"] == [
        {"id": "a", "name": "A", "type": "acp"},
        {"id": "b", "name": "B", "type": "acp"},
    ]
    assert init["current"] == "b"
    assert init["config_errors"] == [
        {"path": "agents.x.command", "message": "wymagane", "line": None}
    ]
    assert init["theme"] == "dark"
    assert init["font_size"] == 14


def test_default_agent_keyword_overrides_config() -> None:
    controller, sink, _, _ = make(config=make_config("a", "b", default="b"), default_agent="a")
    controller.ready()
    assert sink.events[0]["current"] == "a"


# -- turns -----------------------------------------------------------------------------------


async def test_turn_dispatch_order() -> None:
    controller, sink, backend, created = make(
        [TextDelta("Echo: "), ThinkingDelta("hmm"), TextDelta("hi"), Done("end_turn")]
    )
    controller.send("hi")
    await settle(controller)
    assert sink.events == [
        {"type": "turn_start"},
        {"type": "text_delta", "text": "Echo: "},
        {"type": "thinking_delta", "text": "hmm"},
        {"type": "text_delta", "text": "hi"},
        {"type": "done", "stop_reason": "end_turn"},
    ]
    assert created == ["echo"]
    assert backend.prompts == [("s1", [{"type": "text", "text": "hi"}])]
    assert backend.closed_iterators == 1
    assert controller.messages == [
        {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "parts": [{"type": "text", "text": "Echo: hi"}],
            "thinking": "hmm",
            "stop_reason": "end_turn",
        },
    ]


async def test_session_is_created_lazily_and_reused() -> None:
    controller, sink, backend, _ = make([Done("end_turn")])
    assert backend.sessions == []
    controller.send("a")
    await settle(controller)
    controller.send("b")
    await settle(controller)
    assert backend.sessions == ["s1"]
    assert [p[0] for p in backend.prompts] == ["s1", "s1"]
    assert sink.types().count("done") == 2


async def test_send_during_turn_is_rejected_with_error() -> None:
    controller, sink, backend, _ = make(["wait"])
    controller.send("first")
    await asyncio.sleep(0.02)
    controller.send("second")
    assert sink.events[-1] == {
        "type": "error",
        "message": strings.CTRL_TURN_RUNNING,
        "kind": "other",
    }
    assert len(backend.prompts) == 1
    controller.cancel()
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}


async def test_cancel_calls_backend_cancel_once() -> None:
    controller, sink, backend, _ = make(["wait"])
    controller.send("long")
    await asyncio.sleep(0.02)
    controller.cancel()
    controller.cancel()
    controller.cancel()
    await settle(controller)
    assert backend.cancels == ["s1"]
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    assert sink.types().count("done") == 1
    # Chunks the agent sends before its cancelled response still belong to the turn.
    assert {"type": "text_delta", "text": "late chunk"} in sink.events
    controller.cancel()  # after the turn: nothing happens
    await settle(controller)
    assert backend.cancels == ["s1"]


async def test_cancel_without_turn_is_noop() -> None:
    controller, sink, backend, _ = make()
    controller.cancel()
    assert sink.events == []
    assert backend.cancels == []


async def test_cancel_while_session_is_created_ends_turn_at_once() -> None:
    controller, sink, backend, _ = make([TextDelta("x"), Done("end_turn")])
    backend.session_gate = asyncio.Event()
    controller.send("a")
    await asyncio.sleep(0.02)
    controller.cancel()
    assert sink.events == [{"type": "turn_start"}, {"type": "done", "stop_reason": "cancelled"}]
    assert not controller.busy
    backend.session_gate.set()
    await settle(controller)
    assert backend.prompts == []  # the prompt of the cancelled turn was never sent
    assert backend.sessions == ["s1"]
    # The next turn reuses the session that was being created.
    controller.send("b")
    await settle(controller)
    assert backend.sessions == ["s1"]
    assert backend.prompts == [("s1", [{"type": "text", "text": "b"}])]
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}


async def test_backend_error_event_then_next_turn_works() -> None:
    backend = FakeBackend([TextDelta("a"), Error("boom", "crashed", stderr="boom")])
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    assert sink.events[-1]["type"] == "error"
    assert sink.events[-1]["message"] == "boom"
    assert sink.events[-1]["kind"] == "crashed"
    assert sink.events[-1]["stderr"] == "boom"
    assert not controller.busy

    backend.script = [TextDelta("ok"), Done("end_turn")]
    controller.send("y")
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}
    # The crashed session is not reused.
    assert backend.sessions == ["s1", "s2"]


async def test_session_error_is_reported_and_retried() -> None:
    backend = FakeBackend([Done("end_turn")], session_error=Error("no login", "auth"))
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    assert sink.events == [
        {"type": "turn_start"},
        {
            # S4-T3: backend errors carry the chat texts of app/strings.py.
            "type": "error",
            "kind": "auth",
            "title": strings.CHAT_ERROR_TITLES["auth"],
            "message": strings.CHAT_AUTH_MESSAGE,
            "hint": strings.CHAT_ERROR_HINTS["auth"],
            "stderr": None,
            "stderr_label": None,
            "auth_methods": [],
            "methods_label": strings.CHAT_AUTH_NO_METHODS,
            "blocked": False,
        },
    ]
    backend.session_error = None
    controller.send("y")
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}


async def test_unexpected_exception_becomes_error() -> None:
    class Broken(FakeBackend):
        async def send(self, session_id, prompt):
            raise RuntimeError("secret detail")
            yield  # pragma: no cover

    controller, sink, _, _ = make(backend=Broken())
    controller.send("x")
    await settle(controller)
    assert sink.events[-1] == {"type": "error", "message": strings.CTRL_UNEXPECTED, "kind": "other"}
    assert "secret detail" not in str(sink.events)


async def test_iterator_without_done_ends_with_error() -> None:
    controller, sink, _, _ = make([TextDelta("a")])
    controller.send("x")
    await settle(controller)
    assert sink.events[-1]["type"] == "error"


async def test_permission_request_is_dispatched_and_not_answered_automatically() -> None:
    # S4-T2 replaced the S3 behaviour (reject at once): the UI asks the user.
    request = PermissionRequest("p1", options=[PermissionOption("allow", "Allow", "allow_once")])
    controller, sink, backend, _ = make([request, Done("end_turn")])
    controller.send("x")
    await settle(controller)
    assert backend.permissions == []
    assert sink.types() == ["turn_start", "permission_request", "done"]


async def test_no_agent_send_answers_error() -> None:
    controller, sink, _, created = make(config=make_config())
    controller.send("x")
    assert sink.events == [{"type": "error", "message": strings.CTRL_NO_AGENT, "kind": "other"}]
    assert created == []
    assert not controller.busy


async def test_unsupported_agent_type_answers_error() -> None:
    config = make_config()
    config.agents["api"] = ApiAgent(id="api", name="Api", endpoint="https://x", model="m")
    sink = ListSink()

    def factory(agent):
        raise NotImplementedError

    controller = ChatController(config, sink, factory)
    controller.send("x")
    assert sink.events == [
        {
            "type": "error",
            "message": strings.CTRL_AGENT_UNSUPPORTED.format(name="Api", type="api"),
            "kind": "other",
        }
    ]


@pytest.mark.parametrize("text", ["", "   \n"])
async def test_empty_prompt_answers_error(text) -> None:
    controller, sink, backend, _ = make([Done("end_turn")])
    controller.send(text)
    assert sink.types() == ["error"]
    assert backend.prompts == []


async def test_new_chat_creates_new_session() -> None:
    controller, sink, backend, _ = make([Done("end_turn")])
    controller.send("a")
    await settle(controller)
    controller.new_chat()
    assert sink.events[-1] == {"type": "conversation", "id": None, "messages": []}
    assert controller.messages == []
    controller.send("b")
    await settle(controller)
    assert backend.sessions == ["s1", "s2"]
    assert [p[0] for p in backend.prompts] == ["s1", "s2"]


async def test_new_chat_during_turn_stops_it_without_late_events() -> None:
    controller, sink, backend, _ = make([TextDelta("a"), "wait"])
    controller.send("x")
    await asyncio.sleep(0.02)
    controller.new_chat()
    tail = sink.events[-2:]
    assert tail == [
        {"type": "done", "stop_reason": "cancelled"},
        {"type": "conversation", "id": None, "messages": []},
    ]
    count = len(sink.events)
    await settle(controller)
    assert len(sink.events) == count  # nothing of the old turn after its done
    assert backend.closed_iterators == 1
    assert controller.messages == []
    assert not controller.busy


async def test_every_send_gets_exactly_one_terminal_event() -> None:
    controller, sink, backend, _ = make([TextDelta("a"), Done("end_turn")])
    for text in ["1", "2", "", "3"]:
        controller.send(text)
        await settle(controller)
    terminals = [e for e in sink.events if e["type"] in ("done", "error")]
    assert len(terminals) == 4


async def test_no_text_delta_after_terminal_event() -> None:
    controller, sink, backend, _ = make(["wait"])
    controller.send("x")
    await asyncio.sleep(0.02)
    controller.cancel()
    await settle(controller)
    seen_end = False
    for event in sink.events:
        if event["type"] in ("done", "error"):
            seen_end = True
        elif seen_end:
            assert event["type"] != "text_delta"


async def test_close_ends_running_turn() -> None:
    controller, sink, backend, _ = make(["wait"])
    controller.send("x")
    await asyncio.sleep(0.02)
    await controller.close()
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    assert not controller.busy
    assert backend.closed_iterators == 1


async def test_failing_sink_does_not_break_the_turn() -> None:
    class Failing(ListSink):
        def dispatch(self, event):
            super().dispatch(event)
            if event["type"] == "text_delta":
                raise RuntimeError("page gone")

    backend = FakeBackend([TextDelta("a"), Done("end_turn")])
    sink = Failing()
    controller = ChatController(make_config("echo"), sink, lambda _a: backend)
    controller.send("x")
    await settle(controller)
    assert sink.types() == ["turn_start", "text_delta", "done"]


# -- theme (S3-T4) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "system_dark", "expected"),
    [
        ("system", False, "light"),
        ("system", True, "dark"),
        ("light", True, "light"),
        ("dark", False, "dark"),
    ],
)
def test_init_theme_combines_setting_and_desktop(setting, system_dark, expected) -> None:
    config = make_config("a")
    config.chat.theme = setting
    controller, sink, _, _ = make(config=config, system_dark=lambda: system_dark)
    controller.ready()
    assert sink.events[0]["theme"] == expected
    assert resolve_theme(setting, system_dark) == expected


def test_refresh_theme_sends_init_again() -> None:
    dark = [False]
    controller, sink, _, _ = make(config=make_config("a"), system_dark=lambda: dark[0])
    controller.ready()
    dark[0] = True
    controller.refresh_theme()
    assert [e["type"] for e in sink.events] == ["init", "init"]
    assert [e["theme"] for e in sink.events] == ["light", "dark"]
    assert sink.events[1]["current"] == "a"
