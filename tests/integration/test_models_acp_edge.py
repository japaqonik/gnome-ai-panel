"""Tester additions (S4-T4): config options with the real AcpBackend and a minimal inline agent.

- ``session/set_config_option`` that the agent never answers ends with a ``timeout`` error
  after ``startup_timeout_s`` (it used to wait forever) and the controller shows a notice;
- ``config_option_update`` sent outside a turn is kept and reported by ``config_options()``;
- an answer without ``configOptions`` keeps the old list in the backend.
"""

import asyncio
import sys
import textwrap
from pathlib import Path

import pytest

from app import backends
from app.backends.base import BackendError
from app.config import AcpAgent, Config
from app.controller import ChatController
from tests.integration.test_controller_acp import ListSink, wait_for

AGENT = textwrap.dedent(
    """
    import json, sys
    MODE = sys.argv[1]
    def opts(current):
        return [{"id": "model", "name": "Model", "category": "model", "type": "select",
                 "currentValue": current,
                 "options": [{"value": "a", "name": "A"}, {"value": "b", "name": "B"}]}]
    def out(obj):
        sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        msg = json.loads(line)
        method, rid = msg.get("method"), msg.get("id")
        if method == "initialize":
            out({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": 1,
                 "agentCapabilities": {}, "authMethods": []}})
        elif method == "session/new":
            result = {"sessionId": "S", "configOptions": opts("a")}
            out({"jsonrpc": "2.0", "id": rid, "result": result})
            if MODE in ("update", "update-late"):
                if MODE == "update-late":
                    import time; time.sleep(0.3)
                update = {"sessionUpdate": "config_option_update", "configOptions": opts("b")}
                params = {"sessionId": "S", "update": update}
                out({"jsonrpc": "2.0", "method": "session/update", "params": params})
        elif method == "session/set_config_option":
            if MODE == "silent":
                continue
            out({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "session/prompt":
            out({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
    """
)


def make_agent(tmp_path: Path, mode: str, timeout: float = 1.0) -> AcpAgent:
    script = tmp_path / "mini_agent.py"
    script.write_text(AGENT)
    return AcpAgent(
        id=f"mini-{mode}",
        name="Mini",
        command=sys.executable,
        args=[str(script), mode],
        cwd=tmp_path,
        startup_timeout_s=timeout,
    )


async def test_unanswered_set_config_option_times_out(isolated_env, tmp_path) -> None:
    agent = make_agent(tmp_path, "silent", timeout=1.0)
    backend = backends.get_backend(agent)
    try:
        session_id = await backend.new_session()
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(BackendError) as info:
            await asyncio.wait_for(backend.set_option(session_id, "model", "b"), 10)
        assert info.value.kind == "timeout"
        assert loop.time() - start < 5
        assert backend.config_options(session_id)[0]["currentValue"] == "a"
    finally:
        await backends.close_all()


async def test_controller_shows_notice_when_set_option_times_out(isolated_env, tmp_path) -> None:
    agent = make_agent(tmp_path, "silent", timeout=1.0)
    config = Config(path=tmp_path / "config.toml", agents={agent.id: agent})
    sink = ListSink()
    controller = ChatController(config, sink, lambda a: backends.get_backend(a))
    try:
        controller.send("x")
        await wait_for(lambda: not controller.busy)
        controller.set_option("model", "b")
        await wait_for(lambda: "notice" in sink.types(), timeout=10)
        notice = next(e for e in sink.events if e["type"] == "notice")
        assert notice["kind"] == "option_failed"
        last = [e for e in sink.events if e["type"] == "config_options"][-1]
        assert last["options"][0]["currentValue"] == "a"
    finally:
        await controller.close()
        await backends.close_all()


async def test_config_option_update_outside_turn_is_kept(isolated_env, tmp_path) -> None:
    agent = make_agent(tmp_path, "update-late")
    backend = backends.get_backend(agent)
    try:
        session_id = await backend.new_session()
        await wait_for(lambda: backend.config_options(session_id)[0]["currentValue"] == "b")
    finally:
        await backends.close_all()


async def test_config_option_update_right_after_session_new_is_kept(isolated_env, tmp_path) -> None:
    # The agent sends the update in the same write burst as the session/new answer.
    agent = make_agent(tmp_path, "update")
    backend = backends.get_backend(agent)
    try:
        session_id = await backend.new_session()
        await wait_for(
            lambda: backend.config_options(session_id)[0]["currentValue"] == "b", timeout=3
        )
    finally:
        await backends.close_all()


async def test_answer_without_config_options_keeps_the_list(isolated_env, tmp_path) -> None:
    agent = make_agent(tmp_path, "empty")
    backend = backends.get_backend(agent)
    try:
        session_id = await backend.new_session()
        assert await backend.set_option(session_id, "model", "b") is None
        assert backend.config_options(session_id)[0]["currentValue"] == "a"
    finally:
        await backends.close_all()
