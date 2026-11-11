"""Tester additions (S3-T3): ChatController with the real AcpBackend and the fake agent.

The UI contract with a real agent process (one terminal event per send, no ``text_delta``
after it, one ``session/cancel`` for repeated cancels) and that no agent process survives
``close_all()``, including after ``new_chat`` in the middle of a turn.
"""

import asyncio
import os
import sys
from pathlib import Path

from app import backends
from app.config import AcpAgent, Config
from app.controller import ChatController

FAKE = Path(__file__).resolve().parents[1] / "fakes" / "fake_acp_agent.py"


class ListSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def dispatch(self, event: dict) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z")
    except (FileNotFoundError, ProcessLookupError):
        return True


async def wait_for(predicate, timeout: float = 15.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def controller_for(tmp_path: Path, scenario: str) -> tuple[ChatController, ListSink]:
    agent = AcpAgent(
        id=f"fake-{scenario}",
        name=f"Fake {scenario}",
        command=sys.executable,
        args=[str(FAKE), "--scenario", scenario],
        cwd=tmp_path / scenario,
    )
    config = Config(path=tmp_path / "config.toml", agents={agent.id: agent})
    sink = ListSink()
    controller = ChatController(config, sink, lambda a: backends.get_backend(a))
    return controller, sink


def after_terminal(events: list[dict]) -> list[dict]:
    for index, event in enumerate(events):
        if event["type"] in ("done", "error"):
            return events[index + 1 :]
    raise AssertionError(f"no terminal event in {events}")


async def test_repeated_cancel_of_slow_turn_with_real_agent(isolated_env, tmp_path) -> None:
    controller, sink = controller_for(tmp_path, "slow")
    try:
        controller.send("długo")
        await wait_for(lambda: "text_delta" in sink.types())
        for _ in range(4):
            controller.cancel()
        await wait_for(lambda: not controller.busy)
        await asyncio.sleep(0.6)  # the fake sends a chunk every 200 ms; none may follow
        assert [e for e in sink.events if e["type"] in ("done", "error")] == [
            {"type": "done", "stop_reason": "cancelled"}
        ]
        assert after_terminal(sink.events) == []
        # The next turn on the same session works.
        controller.send("znowu")
        await wait_for(lambda: sink.types().count("text_delta") > 0 and controller.busy)
        controller.cancel()
        await wait_for(lambda: not controller.busy)
        assert sink.types().count("done") == 2
    finally:
        await controller.close()
        await backends.close_all()


async def test_new_chat_mid_turn_then_close_leaves_no_agent(isolated_env, tmp_path) -> None:
    controller, sink = controller_for(tmp_path, "slow")
    pid = None
    try:
        controller.send("długo")
        await wait_for(lambda: "text_delta" in sink.types())
        pid = controller._backend.pid
        assert pid is not None and not gone(pid)
        controller.new_chat()
        assert sink.types()[-2:] == ["done", "conversation"]
        count = len(sink.events)
        await asyncio.sleep(0.6)
        assert len(sink.events) == count  # no late chunks of the old turn
        assert not controller.busy
        # A new turn after new_chat uses the same process and a new session.
        before = controller.session_id
        controller.send("nowa")
        await wait_for(lambda: controller.session_id is not None)
        assert controller.session_id != before
        assert controller._backend.pid == pid
    finally:
        await controller.close()
        await backends.close_all()
    assert pid is not None
    await wait_for(lambda: gone(pid), timeout=5)


async def test_echo_turns_and_rejected_send_keep_contract(isolated_env, tmp_path) -> None:
    controller, sink = controller_for(tmp_path, "echo")
    try:
        for text in ["a", "", "b"]:
            controller.send(text)
            await wait_for(lambda: not controller.busy)
        terminals = [e for e in sink.events if e["type"] in ("done", "error")]
        assert [e["type"] for e in terminals] == ["done", "error", "done"]
        text = "".join(e["text"] for e in sink.events if e["type"] == "text_delta")
        assert "Echo: a" in text and "Echo: b" in text
        pid = controller._backend.pid
    finally:
        await controller.close()
        await backends.close_all()
    await wait_for(lambda: gone(pid), timeout=5)
