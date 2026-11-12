"""ChatController + real AcpBackend + fake agent ``models``: config options from
``session/new``, ``session/set_config_option`` and the updated ``currentValue`` (S4-T4, FR-12)."""

import json
import sys
from pathlib import Path

from app import backends
from app.backends.base import BackendError
from app.config import AcpAgent, Config
from app.controller import ChatController
from tests.integration.test_controller_acp import FAKE, ListSink, wait_for


def models_controller(tmp_path: Path) -> tuple[ChatController, ListSink, Path]:
    record = tmp_path / "record.jsonl"
    agent = AcpAgent(
        id="fake-models",
        name="Fake models",
        command=sys.executable,
        args=[str(FAKE), "--scenario", "models", "--record", str(record)],
        cwd=tmp_path / "models",
    )
    config = Config(path=tmp_path / "config.toml", agents={agent.id: agent})
    sink = ListSink()
    controller = ChatController(config, sink, lambda a: backends.get_backend(a))
    return controller, sink, record


def recorded(record: Path, method: str) -> list[dict]:
    lines = [json.loads(line) for line in record.read_text().splitlines()]
    return [line["params"] for line in lines if line["method"] == method]


def reply(sink: ListSink, start: int) -> str:
    return "".join(e["text"] for e in sink.events[start:] if e["type"] == "text_delta")


def model_events(sink: ListSink) -> list[dict]:
    return [
        next(o for o in e["options"] if o["category"] == "model")
        for e in sink.events
        if e["type"] == "config_options" and e["options"]
    ]


async def test_model_change_goes_to_the_agent(isolated_env, tmp_path) -> None:
    controller, sink, record = models_controller(tmp_path)
    try:
        controller.send("a")
        await wait_for(lambda: not controller.busy)
        assert reply(sink, 0) == "[fake-small] Echo: a"
        [model] = model_events(sink)
        assert model["id"] == "model"
        assert model["currentValue"] == "fake-small"
        assert [o["value"] for o in model["options"]] == ["fake-small", "fake-large"]

        controller.set_option("model", "fake-large")
        await wait_for(lambda: len(model_events(sink)) == 2)
        assert model_events(sink)[-1]["currentValue"] == "fake-large"
        session_id = controller.session_id
        assert recorded(record, "session/set_config_option") == [
            {"sessionId": session_id, "configId": "model", "value": "fake-large"}
        ]
        assert controller._backend.config_options(session_id)[0]["currentValue"] == "fake-large"

        start = len(sink.events)
        controller.send("b")
        await wait_for(lambda: not controller.busy)
        assert reply(sink, start) == "[fake-large] Echo: b"
    finally:
        await controller.close()
        await backends.close_all()


async def test_value_not_offered_is_not_sent(isolated_env, tmp_path) -> None:
    controller, sink, record = models_controller(tmp_path)
    try:
        controller.send("a")
        await wait_for(lambda: not controller.busy)
        controller.set_option("model", "fake-huge")
        await wait_for(lambda: len(model_events(sink)) == 2)
        assert model_events(sink)[-1]["currentValue"] == "fake-small"
        assert recorded(record, "session/set_config_option") == []
    finally:
        await controller.close()
        await backends.close_all()


async def test_backend_set_option_rejected_by_agent_raises(isolated_env, tmp_path) -> None:
    controller, _, _ = models_controller(tmp_path)
    try:
        controller.send("a")
        await wait_for(lambda: not controller.busy)
        backend = controller._backend
        try:
            await backend.set_option(controller.session_id, "model", "fake-huge")
        except BackendError as exc:
            assert exc.kind == "protocol"
        else:
            raise AssertionError("set_option with an invalid value did not fail")
        # The stored options are unchanged after the failure.
        assert backend.config_options(controller.session_id)[0]["currentValue"] == "fake-small"
    finally:
        await controller.close()
        await backends.close_all()
