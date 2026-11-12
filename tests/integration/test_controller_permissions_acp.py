"""ChatController + real AcpBackend + fake agent, scenario ``permission`` (S4-T2, FR-11).

The fake agent records the client's answer to ``session/request_permission`` in the
``--record`` file, so the tests see exactly what the agent received.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from app import backends
from app.config import AcpAgent, Config
from app.controller import ChatController
from tests.integration.test_controller_acp import ListSink, wait_for

FAKE = Path(__file__).resolve().parents[1] / "fakes" / "fake_acp_agent.py"


def permission_controller(tmp_path: Path) -> tuple[ChatController, ListSink, Path]:
    record = tmp_path / "record.jsonl"
    agent = AcpAgent(
        id="fake-perm",
        name="Fake perm",
        command=sys.executable,
        args=[str(FAKE), "--scenario", "permission", "--record", str(record)],
        cwd=tmp_path / "perm",
    )
    config = Config(path=tmp_path / "config.toml", agents={agent.id: agent})
    sink = ListSink()
    controller = ChatController(config, sink, lambda a: backends.get_backend(a))
    return controller, sink, record


def answers(record: Path) -> list[dict]:
    if not record.exists():
        return []
    lines = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
    return [e["result"] for e in lines if e["method"] == "session/request_permission"]


def tool_statuses(sink: ListSink) -> list[str]:
    return [e["status"] for e in sink.events if e["type"] == "tool_update" and "status" in e]


def reply_text(sink: ListSink) -> str:
    return "".join(e["text"] for e in sink.events if e["type"] == "text_delta")


async def ask(controller: ChatController, sink: ListSink) -> dict:
    controller.send("zrób")
    await wait_for(lambda: "permission_request" in sink.types())
    return next(e for e in sink.events if e["type"] == "permission_request")


@pytest.mark.parametrize(
    ("option", "status", "text"),
    [("allow", "completed", "Zezwolono"), ("reject", "failed", "Odmowa")],
)
async def test_answer_from_the_ui_reaches_the_agent(
    isolated_env, tmp_path, option, status, text
) -> None:
    controller, sink, record = permission_controller(tmp_path)
    try:
        request = await ask(controller, sink)
        assert request["title"] == "Zapis pliku out.txt"
        assert request["raw_input"] == {"path": "out.txt", "content": "x"}
        assert [(o["id"], o["kind"]) for o in request["options"]] == [
            ("allow", "allow_once"),
            ("reject", "reject_once"),
        ]
        await asyncio.sleep(0.2)
        assert controller.busy and answers(record) == []  # nothing chosen automatically
        controller.permission(request["request_id"], option)
        await wait_for(lambda: not controller.busy)
        assert answers(record) == [{"outcome": {"outcome": "selected", "optionId": option}}]
        assert tool_statuses(sink)[-1] == status
        assert reply_text(sink) == text
        assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}
    finally:
        await controller.close()
        await backends.close_all()


async def test_null_answer_selects_the_agents_reject_option(isolated_env, tmp_path) -> None:
    controller, sink, record = permission_controller(tmp_path)
    try:
        request = await ask(controller, sink)
        controller.permission(request["request_id"], None)
        await wait_for(lambda: not controller.busy)
        assert answers(record) == [{"outcome": {"outcome": "selected", "optionId": "reject"}}]
        assert tool_statuses(sink)[-1] == "failed"
    finally:
        await controller.close()
        await backends.close_all()


async def test_cancel_with_open_request_answers_cancelled(isolated_env, tmp_path) -> None:
    controller, sink, record = permission_controller(tmp_path)
    try:
        request = await ask(controller, sink)
        controller.cancel()
        await wait_for(lambda: not controller.busy)
        assert answers(record) == [{"outcome": {"outcome": "cancelled"}}]
        assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
        # A late answer of the closed dialog changes nothing.
        controller.permission(request["request_id"], "allow")
        await asyncio.sleep(0.1)
        assert len(answers(record)) == 1
    finally:
        await controller.close()
        await backends.close_all()


async def test_new_chat_with_open_request_answers_cancelled(isolated_env, tmp_path) -> None:
    controller, sink, record = permission_controller(tmp_path)
    try:
        await ask(controller, sink)
        controller.new_chat()
        await wait_for(lambda: answers(record) != [])
        assert answers(record) == [{"outcome": {"outcome": "cancelled"}}]
        assert sink.types()[-2:] == ["done", "conversation"]
    finally:
        await controller.close()
        await backends.close_all()
