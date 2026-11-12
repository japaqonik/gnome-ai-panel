"""ChatController: agent selection and session config options (S4-T4)."""

import asyncio

from app import strings
from app.backends.base import ConfigOptions, Done, Error, TextDelta
from app.config import ApiAgent
from app.controller import ChatController, normalize_config_options, option_values
from tests.unit.test_controller import FakeBackend, ListSink, make, make_config, settle

MODEL = {
    "id": "model",
    "name": "Model",
    "category": "model",
    "type": "select",
    "currentValue": "small",
    "options": [{"value": "small", "name": "Small"}, {"value": "large", "name": "Large"}],
}


def model_option(current: str = "small") -> dict:
    return {**MODEL, "currentValue": current}


def options_events(sink: ListSink) -> list[list[dict]]:
    return [e["options"] for e in sink.events if e["type"] == "config_options"]


def make_agents(*ids: str, **kwargs):
    """Controller over ``ids`` with one FakeBackend per agent (created lazily)."""
    sink = ListSink()
    backends: dict[str, FakeBackend] = {}
    changes: list[str | None] = []

    def factory(agent):
        return backends.setdefault(agent.id, FakeBackend([Done("end_turn")]))

    controller = ChatController(
        make_config(*ids), sink, factory, on_agent_changed=changes.append, **kwargs
    )
    return controller, sink, backends, changes


# -- normalize_config_options ------------------------------------------------------------------


def test_normalize_keeps_select_options_in_order() -> None:
    mode = {**MODEL, "id": "mode", "category": "mode"}
    assert normalize_config_options([mode, MODEL]) == [mode, MODEL]


def test_normalize_grouped_values() -> None:
    grouped = {
        **MODEL,
        "options": [
            {"group": "fast", "name": "Szybkie", "options": [{"value": "small", "name": "S"}]},
            {"group": "big", "options": [{"value": "large", "name": "L", "description": "d"}]},
            {"group": "empty", "name": "Pusta", "options": []},
            {"name": "no group id", "options": [{"value": "x", "name": "X"}]},
        ],
    }
    [option] = normalize_config_options([grouped])
    assert option["options"] == [
        {"group": "fast", "name": "Szybkie", "options": [{"value": "small", "name": "S"}]},
        {
            "group": "big",
            "name": "big",
            "options": [{"value": "large", "name": "L", "description": "d"}],
        },
    ]
    assert option_values(option) == {"small", "large"}


def test_normalize_drops_unusable_entries() -> None:
    options = [
        "text",
        None,
        {**MODEL, "type": "boolean", "currentValue": True},
        {**MODEL, "currentValue": None},
        {**MODEL, "id": ""},
        {**MODEL, "options": "small"},
        {**MODEL, "options": [{"name": "no value"}, 7]},
        {
            **MODEL,
            "id": "ok",
            "name": None,
            "category": 5,
            "options": [{"value": "v"}, {"value": 3}],
        },
    ]
    assert normalize_config_options(options) == [
        {
            "id": "ok",
            "name": "ok",
            "category": None,
            "type": "select",
            "currentValue": "small",
            "options": [{"value": "v", "name": "v"}],
        }
    ]
    assert normalize_config_options("nope") == []
    assert normalize_config_options(None) == []


def test_normalize_caps_long_texts_and_counts() -> None:
    values = [{"value": f"v{i}", "name": "n" * 1000} for i in range(600)]
    [option] = normalize_config_options([{**MODEL, "options": values}])
    assert len(option["options"]) == 500
    assert len(option["options"][0]["name"]) == 500
    many = [{**MODEL, "id": f"o{i}"} for i in range(40)]
    assert len(normalize_config_options(many)) == 32


# -- select_agent ------------------------------------------------------------------------------


async def test_select_agent_starts_new_conversation_with_the_new_agent() -> None:
    controller, sink, backends, changes = make_agents("a", "b")
    controller.send("one")
    await settle(controller)
    sink.events.clear()

    assert controller.select_agent("b") is True
    assert controller.agent_id == "b"
    assert changes == ["b"]
    assert sink.types() == ["conversation", "init"]
    assert sink.events[1]["current"] == "b"
    assert controller.messages == []

    controller.send("two")
    await settle(controller)
    assert backends["b"].prompts == [("s1", [{"type": "text", "text": "two"}])]
    assert len(backends["a"].prompts) == 1


async def test_select_unknown_agent_is_refused_and_init_repeated() -> None:
    controller, sink, _, changes = make_agents("a", "b")
    assert controller.select_agent("missing") is False
    assert controller.agent_id == "a"
    assert changes == []
    assert sink.types() == ["init"]
    assert sink.events[0]["current"] == "a"


async def test_select_current_agent_changes_nothing() -> None:
    controller, sink, _, changes = make_agents("a", "b")
    controller.send("x")
    await settle(controller)
    sink.events.clear()
    assert controller.select_agent("a") is True
    assert sink.events == []
    assert changes == []
    assert len(controller.messages) == 2


async def test_select_agent_during_turn_stops_it_without_late_events() -> None:
    controller, sink, backends, _ = make_agents("a", "b")
    backends["a"] = FakeBackend([TextDelta("x"), "wait"])
    controller.send("x")
    await asyncio.sleep(0.05)
    controller.select_agent("b")
    await settle(controller)
    types = sink.types()
    assert types[-3:] == ["done", "conversation", "init"]
    assert sink.events[-3] == {"type": "done", "stop_reason": "cancelled"}
    assert not controller.busy


async def test_agents_property_lists_valid_agents() -> None:
    controller, *_ = make_agents("a", "b")
    assert controller.agents == [("a", "A"), ("b", "B")]


async def test_select_api_agent_then_send_is_not_supported_yet() -> None:
    config = make_config("a")
    config.agents["chat"] = ApiAgent(id="chat", name="Czat", endpoint="https://x", model="m")
    sink = ListSink()

    def factory(agent):
        if agent.type != "acp":
            raise NotImplementedError
        return FakeBackend([Done("end_turn")])

    controller = ChatController(config, sink, factory)
    assert controller.select_agent("chat") is True
    init = sink.events[-1]
    assert init["current"] == "chat"
    assert {"id": "chat", "name": "Czat", "type": "api"} in init["agents"]
    sink.events.clear()
    controller.send("x")
    assert sink.events == [
        {
            "type": "error",
            "message": strings.CTRL_AGENT_UNSUPPORTED.format(name="Czat", type="api"),
            "kind": "other",
        }
    ]
    # Back to the ACP agent: it works again.
    controller.select_agent("a")
    controller.send("y")
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}


async def test_agent_change_callback_failure_is_logged(caplog) -> None:
    def broken(_agent_id):
        raise RuntimeError("boom")

    controller = ChatController(
        make_config("a", "b"), ListSink(), lambda a: FakeBackend(), on_agent_changed=broken
    )
    assert controller.select_agent("b") is True
    assert "agent change callback failed" in caplog.text


# -- config options ----------------------------------------------------------------------------


async def test_session_options_are_dispatched_after_session_creation() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option(), {"id": "flag", "type": "boolean", "currentValue": True}]
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    assert sink.types() == ["turn_start", "config_options", "done"]
    assert options_events(sink) == [[MODEL]]
    assert controller.config_options == [MODEL]


async def test_no_config_options_event_without_options() -> None:
    controller, sink, _, _ = make([Done("end_turn")])
    controller.send("x")
    await settle(controller)
    assert "config_options" not in sink.types()


async def test_set_option_forwards_and_updates_options() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option()]
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    sink.events.clear()

    controller.set_option("model", "large")
    await settle(controller)
    assert backend.option_calls == [("s1", "model", "large")]
    assert options_events(sink) == [[model_option("large")]]
    assert controller.config_options == [model_option("large")]


async def test_set_option_uses_config_options_when_backend_returns_none() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option()]

    async def set_option(session_id, config_id, value):
        backend.options[0]["currentValue"] = value
        return None

    backend.set_option = set_option
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    controller.set_option("model", "large")
    await settle(controller)
    assert options_events(sink)[-1] == [model_option("large")]


async def test_set_option_with_value_not_offered_is_not_forwarded() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option()]
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    sink.events.clear()
    controller.set_option("model", "huge")
    controller.set_option("other", "small")
    controller.set_option("model", "small")  # the current value: nothing to change
    await settle(controller)
    assert backend.option_calls == []
    assert options_events(sink) == [[MODEL], [MODEL], [MODEL]]


async def test_set_option_without_session_is_dropped() -> None:
    controller, sink, backend, _ = make([Done("end_turn")])
    controller.set_option("model", "large")
    await settle(controller)
    assert backend.option_calls == []
    assert sink.events == [{"type": "config_options", "options": []}]


async def test_set_option_failure_restores_options_and_shows_notice() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option()]
    backend.option_error = Error("Invalid params", "protocol")
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    sink.events.clear()
    controller.set_option("model", "large")
    await settle(controller)
    assert sink.events == [
        {"type": "config_options", "options": [MODEL]},
        {
            "type": "notice",
            "kind": "option_failed",
            "text": strings.CTRL_OPTION_FAILED.format(name="Model", reason="Invalid params"),
        },
    ]


async def test_unexpected_set_option_failure_is_reported() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option()]

    async def set_option(session_id, config_id, value):
        raise RuntimeError("bug")

    backend.set_option = set_option
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    sink.events.clear()
    controller.set_option("model", "large")
    await settle(controller)
    assert sink.types() == ["config_options", "notice"]
    assert strings.CTRL_UNEXPECTED in sink.events[1]["text"]


async def test_set_option_answer_after_new_chat_is_dropped() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option()]
    gate = asyncio.Event()
    original = backend.set_option

    async def slow_set_option(*args):
        await gate.wait()
        return await original(*args)

    backend.set_option = slow_set_option
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    controller.set_option("model", "large")
    await asyncio.sleep(0)
    controller.new_chat()
    sink.events.clear()
    gate.set()
    await settle(controller)
    assert sink.events == []
    assert controller.config_options == []


async def test_config_option_update_during_turn_is_dispatched() -> None:
    backend = FakeBackend(
        [TextDelta("a"), ConfigOptions([model_option("large")]), Done("end_turn")]
    )
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    assert sink.types() == ["turn_start", "text_delta", "config_options", "done"]
    assert controller.config_options == [model_option("large")]


async def test_crash_hides_the_options_of_the_lost_session() -> None:
    backend = FakeBackend([Error("Proces agenta zakończył działanie (kod 3).", "crashed")])
    backend.options = [model_option()]
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    assert options_events(sink) == [[MODEL], []]
    assert sink.types()[-1] == "error"
    assert controller.config_options == []


async def test_new_chat_forgets_options() -> None:
    backend = FakeBackend([Done("end_turn")])
    backend.options = [model_option()]
    controller, sink, _, _ = make(backend=backend)
    controller.send("x")
    await settle(controller)
    controller.new_chat()
    assert controller.config_options == []
    controller.set_option("model", "large")
    await settle(controller)
    assert backend.option_calls == []
