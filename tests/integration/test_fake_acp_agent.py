"""tests/fakes/fake_acp_agent.py driven through JsonRpcConnection over real pipes (S2-T3)."""

import asyncio
import base64
import contextlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.backends.jsonrpc import ConnectionClosed, JsonRpcConnection, JsonRpcError

FAKE = Path(__file__).resolve().parent.parent / "fakes" / "fake_acp_agent.py"


class Agent:
    def __init__(self, proc: asyncio.subprocess.Process, conn: JsonRpcConnection) -> None:
        self.proc = proc
        self.conn = conn
        self.updates: list[dict] = []
        self.permission_answer: dict | None = None
        self.permission_requests: list[dict] = []

    def texts(self, kind: str = "agent_message_chunk") -> str:
        return "".join(
            u["update"]["content"]["text"]
            for u in self.updates
            if u["update"]["sessionUpdate"] == kind
        )

    def kinds(self) -> list[str]:
        return [u["update"]["sessionUpdate"] for u in self.updates]

    async def start_session(self, cwd: Path) -> str:
        await self.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        result = await self.conn.request(
            "session/new", {"cwd": str(cwd), "mcpServers": []}, timeout=5
        )
        return result["sessionId"]

    async def prompt(self, session_id: str, text: str, extra: list | None = None) -> str:
        blocks = [{"type": "text", "text": text}, *(extra or [])]
        result = await self.conn.request(
            "session/prompt", {"sessionId": session_id, "prompt": blocks}, timeout=15
        )
        return result["stopReason"]


@contextlib.asynccontextmanager
async def fake_agent(scenario: str, *extra: str, env: dict | None = None):
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(FAKE),
        "--scenario",
        scenario,
        *extra,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    agent: Agent

    async def on_request(method, params):
        agent.permission_requests.append(params)
        return agent.permission_answer

    conn = JsonRpcConnection(
        proc.stdout,
        proc.stdin,
        request_handler=on_request,
        notification_handler=lambda m, p: agent.updates.append(p),
        name=f"fake-{scenario}",
    )
    agent = Agent(proc, conn)
    conn.start()
    try:
        yield agent
    finally:
        await conn.close()
        if proc.returncode is None:
            proc.stdin.close()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                proc.kill()
                await proc.wait()


def test_done_when_printf_initialize_prints_protocol_version() -> None:
    line = '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}\n'
    out = subprocess.run(
        [sys.executable, str(FAKE), "--scenario", "echo"],
        input=line,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert '"protocolVersion": 1' in out.stdout
    response = json.loads(out.stdout.splitlines()[0])
    assert response["id"] == 0
    assert response["result"]["agentInfo"]["name"] == "fake-acp-agent"


async def test_echo_in_three_fragments(tmp_path: Path) -> None:
    async with fake_agent("echo") as agent:
        sid = await agent.start_session(tmp_path)
        assert await agent.prompt(sid, "Cześć") == "end_turn"
        assert agent.kinds() == ["agent_message_chunk"] * 3
        assert agent.texts() == "Echo: Cześć"
        assert {u["sessionId"] for u in agent.updates} == {sid}


async def test_echo_markdown(tmp_path: Path) -> None:
    async with fake_agent("echo") as agent:
        sid = await agent.start_session(tmp_path)
        await agent.prompt(sid, "md: tabela")
        assert "| a | 1 |" in agent.texts()
        assert "```python" in agent.texts()


async def test_thinking(tmp_path: Path) -> None:
    async with fake_agent("thinking") as agent:
        sid = await agent.start_session(tmp_path)
        await agent.prompt(sid, "x")
        assert agent.texts("agent_thought_chunk")
        assert agent.texts() == "Echo: x"


async def test_tool(tmp_path: Path) -> None:
    async with fake_agent("tool") as agent:
        sid = await agent.start_session(tmp_path)
        await agent.prompt(sid, "x")
        assert agent.kinds()[:4] == [
            "agent_thought_chunk",
            "tool_call",
            "tool_call_update",
            "tool_call_update",
        ]
        statuses = [u["update"].get("status") for u in agent.updates[1:4]]
        assert statuses == ["pending", "in_progress", "completed"]


@pytest.mark.parametrize(
    ("answer", "status", "text", "stop"),
    [
        (
            {"outcome": {"outcome": "selected", "optionId": "allow"}},
            "completed",
            "Zezwolono",
            "end_turn",
        ),
        (
            {"outcome": {"outcome": "selected", "optionId": "reject"}},
            "failed",
            "Odmowa",
            "end_turn",
        ),
        ({"outcome": {"outcome": "cancelled"}}, "failed", "", "cancelled"),
    ],
)
async def test_permission(tmp_path: Path, answer, status, text, stop) -> None:
    async with fake_agent("permission") as agent:
        agent.permission_answer = answer
        sid = await agent.start_session(tmp_path)
        assert await agent.prompt(sid, "x") == stop
        [request] = agent.permission_requests
        assert request["sessionId"] == sid
        assert {o["kind"] for o in request["options"]} == {"allow_once", "reject_once"}
        assert agent.updates[-1 if not text else -2]["update"]["status"] == status
        assert agent.texts() == text


async def test_slow_honours_cancel(tmp_path: Path) -> None:
    async with fake_agent("slow") as agent:
        sid = await agent.start_session(tmp_path)
        loop = asyncio.get_running_loop()
        task = asyncio.create_task(agent.prompt(sid, "x"))
        await asyncio.sleep(0.5)
        start = loop.time()
        await agent.conn.notify("session/cancel", {"sessionId": sid})
        assert await task == "cancelled"
        assert loop.time() - start < 2
        assert agent.texts().startswith("fragment 1 ")


async def test_crash_exits_3_with_boom(tmp_path: Path) -> None:
    async with fake_agent("crash") as agent:
        sid = await agent.start_session(tmp_path)
        with pytest.raises(ConnectionClosed):
            await agent.prompt(sid, "x")
        assert await asyncio.wait_for(agent.proc.wait(), 5) == 3
        assert b"boom" in await agent.proc.stderr.read()


async def test_crash_once_uses_marker_in_cwd(tmp_path: Path) -> None:
    async with fake_agent("crash-once") as agent:
        sid = await agent.start_session(tmp_path)
        with pytest.raises(ConnectionClosed):
            await agent.prompt(sid, "x")
    assert (tmp_path / ".fake-acp-crash-once").exists()
    async with fake_agent("crash-once") as agent:
        sid = await agent.start_session(tmp_path)
        assert await agent.prompt(sid, "x") == "end_turn"
        assert agent.texts() == "Echo: x"


async def test_bad_version() -> None:
    async with fake_agent("bad-version") as agent:
        result = await agent.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        assert result["protocolVersion"] == 99


async def test_auth(tmp_path: Path) -> None:
    async with fake_agent("auth") as agent:
        result = await agent.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        assert result["authMethods"][0]["id"] == "fake-login"
        with pytest.raises(JsonRpcError) as info:
            await agent.conn.request("session/new", {"cwd": str(tmp_path), "mcpServers": []})
        assert info.value.code == -32000


async def test_noise_is_ignored(tmp_path: Path) -> None:
    async with fake_agent("noise") as agent:
        sid = await agent.start_session(tmp_path)
        assert await agent.prompt(sid, "abc") == "end_turn"
        assert agent.texts() == "Echo: abc"


async def test_models(tmp_path: Path) -> None:
    async with fake_agent("models") as agent:
        await agent.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        result = await agent.conn.request("session/new", {"cwd": str(tmp_path), "mcpServers": []})
        [option] = result["configOptions"]
        assert option["category"] == "model"
        assert option["currentValue"] == "fake-small"
        sid = result["sessionId"]
        changed = await agent.conn.request(
            "session/set_config_option",
            {"sessionId": sid, "configId": "model", "value": "fake-large"},
        )
        assert changed["configOptions"][0]["currentValue"] == "fake-large"
        await agent.prompt(sid, "x")
        assert agent.texts() == "[fake-large] Echo: x"


async def test_load(tmp_path: Path) -> None:
    async with fake_agent("load") as agent:
        init = await agent.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        assert init["agentCapabilities"]["loadSession"] is True
        await agent.conn.request(
            "session/load", {"sessionId": "sess_old", "cwd": str(tmp_path), "mcpServers": []}
        )
        assert "user_message_chunk" in agent.kinds()
        assert await agent.prompt("sess_old", "x") == "end_turn"


async def test_usage(tmp_path: Path) -> None:
    async with fake_agent("usage") as agent:
        sid = await agent.start_session(tmp_path)
        await agent.prompt(sid, "x")
        usage = agent.updates[-1]["update"]
        assert usage["sessionUpdate"] == "usage_update"
        assert usage["used"] == 1234
        assert usage["cost"]["currency"] == "USD"


async def test_image(tmp_path: Path) -> None:
    async with fake_agent("image") as agent:
        init = await agent.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        assert init["agentCapabilities"]["promptCapabilities"]["image"] is True
        sid = (await agent.conn.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}))[
            "sessionId"
        ]
        image = {
            "type": "image",
            "mimeType": "image/png",
            "data": base64.b64encode(b"12345").decode(),
        }
        await agent.prompt(sid, "opisz", [image])
        assert "Obraz: image/png, 5 bajtów" in agent.texts()


async def test_env(tmp_path: Path) -> None:
    import os

    env = {**os.environ, "SECRET_VAR": "s3cr3t-value"}
    async with fake_agent("env", env=env) as agent:
        sid = await agent.start_session(tmp_path)
        await agent.prompt(sid, "SECRET_VAR")
        assert agent.texts() == "s3cr3t-value"


async def test_two_sessions_in_parallel_are_routed(tmp_path: Path) -> None:
    async with fake_agent("echo") as agent:
        await agent.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        a = (await agent.conn.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}))[
            "sessionId"
        ]
        b = (await agent.conn.request("session/new", {"cwd": str(tmp_path), "mcpServers": []}))[
            "sessionId"
        ]
        assert a != b
        await asyncio.gather(agent.prompt(a, "AAA"), agent.prompt(b, "BBB"))
        by_session: dict[str, str] = {}
        for u in agent.updates:
            by_session[u["sessionId"]] = (
                by_session.get(u["sessionId"], "") + u["update"]["content"]["text"]
            )
        assert by_session == {a: "Echo: AAA", b: "Echo: BBB"}


async def test_record_writes_params_as_json_lines(tmp_path: Path) -> None:
    record = tmp_path / "rec.jsonl"
    async with fake_agent("echo", "--record", str(record)) as agent:
        await agent.conn.request("initialize", {"protocolVersion": 1}, timeout=5)
        result = await agent.conn.request(
            "session/new",
            {"cwd": str(tmp_path), "mcpServers": [{"name": "m"}], "_meta": {"k": "v"}},
        )
        await agent.prompt(result["sessionId"], "x")
    lines = [json.loads(line) for line in record.read_text().splitlines()]
    assert [line["method"] for line in lines] == ["initialize", "session/new", "session/prompt"]
    assert lines[1]["params"]["mcpServers"] == [{"name": "m"}]
    assert lines[1]["params"]["_meta"] == {"k": "v"}


async def test_unknown_method_and_session(tmp_path: Path) -> None:
    async with fake_agent("echo") as agent:
        with pytest.raises(JsonRpcError) as info:
            await agent.conn.request("nope", {}, timeout=5)
        assert info.value.code == -32601
        with pytest.raises(JsonRpcError):
            await agent.prompt("sess_missing", "x")


async def test_exits_on_stdin_eof(tmp_path: Path) -> None:
    async with fake_agent("echo") as agent:
        agent.proc.stdin.close()
        assert await asyncio.wait_for(agent.proc.wait(), 5) == 0
        await asyncio.wait_for(agent.conn.wait_closed(), 5)
