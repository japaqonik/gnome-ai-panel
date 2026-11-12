"""Tester additions (S4-T4): boundary values of ``select_agent``/``set_option`` in the bridge
and agent switching in the controller."""

from app.backends.base import Done
from tests.unit.test_bridge import RecordingHandler, SinkBridge
from tests.unit.test_controller import settle
from tests.unit.test_controller_agents import MODEL, make_agents, options_events


def test_ids_of_exactly_256_characters_are_accepted() -> None:
    handler = RecordingHandler()
    b = SinkBridge(handler)
    b.handle({"type": "select_agent", "id": "a" * 256})
    b.handle({"type": "set_option", "config_id": "c" * 256, "value": "v" * 256})
    assert handler.calls == [
        ("select_agent", "a" * 256),
        ("set_option", "c" * 256, "v" * 256),
    ]


def test_select_agent_without_handler_is_dropped_quietly() -> None:
    b = SinkBridge(None)
    b.handle({"type": "select_agent", "id": "x"})
    b.handle({"type": "set_option", "config_id": "model", "value": "a"})
    assert b.dispatched == []


async def test_options_of_previous_agent_are_not_used_after_switch() -> None:
    controller, sink, backends, changes = make_agents("one", "two")
    controller.send("x")
    await settle(controller)
    backends["one"].options = [MODEL]
    # Options arrive for agent "one"; then the user switches to "two".
    controller._set_options([MODEL])
    assert controller.select_agent("two") is True
    assert controller.config_options == []
    sink.events.clear()
    controller.set_option("model", "large")
    await settle(controller)
    assert backends["one"].option_calls == []
    assert options_events(sink) == [[]]
    assert changes == ["two"]


async def test_switch_back_reuses_the_first_backend_and_new_session() -> None:
    controller, _, backends, changes = make_agents("one", "two")
    controller.send("x")
    await settle(controller)
    first = backends["one"]
    controller.select_agent("two")
    controller.select_agent("one")
    first.script = [Done("end_turn")]
    controller.send("y")
    await settle(controller)
    assert controller.agent_id == "one"
    assert changes == ["two", "one"]
    assert controller.messages[0]["parts"][0]["text"] == "y"
