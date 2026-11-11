"""AcpBackend ⇄ tests/fakes/fake_acp_agent.py over real pipes (S2-T4)."""

import asyncio
import json
import logging
import os
import stat
import sys
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from app.backends import acp as acp_module
from app.backends import close_all, get_backend
from app.backends.acp import AcpBackend
from app.backends.base import (
    BackendError,
    Done,
    Error,
    PermissionRequest,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolUpdate,
    Usage,
)
from app.config import AcpAgent, Command, Literal, McpServer

FAKE = Path(__file__).resolve().parent.parent / "fakes" / "fake_acp_agent.py"


def fake_agent(cwd: Path, scenario: str, *extra: str, **kwargs) -> AcpAgent:
    return AcpAgent(
        id=kwargs.pop("id", f"fake-{scenario}"),
        name=kwargs.pop("name", f"Fake {scenario}"),
        command=sys.executable,
        args=[str(FAKE), "--scenario", scenario, *extra],
        cwd=cwd,
        **kwargs,
    )


@pytest.fixture
def work(isolated_env, tmp_path: Path) -> Path:
    return tmp_path / "work" / "agent"


@pytest.fixture
async def backends() -> AsyncIterator[Callable[..., AcpBackend]]:
    created: list[AcpBackend] = []

    def make(agent: AcpAgent, mcp=None, **kwargs) -> AcpBackend:
        backend = AcpBackend(agent, mcp, **kwargs)
        created.append(backend)
        return backend

    try:
        yield make
    finally:
        for backend in created:
            await backend.close()
        await close_all()


async def collect(backend: AcpBackend, session_id: str, text: str, on_event=None) -> list:
    events = []
    async with asyncio.timeout(15):
        async for event in backend.send(session_id, [{"type": "text", "text": text}]):
            events.append(event)
            if on_event is not None:
                await on_event(event)
    return events


def text_of(events, cls=TextDelta) -> str:
    return "".join(e.text for e in events if isinstance(e, cls))


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def process_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


# -- turns -------------------------------------------------------------------------------------


async def test_echo_streams_text_in_order_and_ends_with_end_turn(backends, work) -> None:
    backend = backends(fake_agent(work, "echo"))
    session = await backend.new_session()
    events = await collect(backend, session, "Cześć")
    deltas = [e.text for e in events if isinstance(e, TextDelta)]
    assert deltas == ["Echo: ", "Cz", "eść"]
    assert events[-1] == Done("end_turn")
    assert backend.protocol_version == 1
    assert backend.agent_info["name"] == "fake-acp-agent"


async def test_cwd_is_created_with_mode_0700(backends, work) -> None:
    backend = backends(fake_agent(work, "echo"))
    await backend.new_session()
    assert work.is_dir()
    assert stat.S_IMODE(work.stat().st_mode) == 0o700


async def test_initialize_params(backends, work, tmp_path) -> None:
    rec = tmp_path / "rec.jsonl"
    backend = backends(fake_agent(work, "echo", "--record", str(rec)))
    await backend.start()
    init = records(rec)[0]
    assert init["method"] == "initialize"
    assert init["params"]["protocolVersion"] == 1
    assert init["params"]["clientCapabilities"] == {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": False,
    }
    assert init["params"]["clientInfo"]["name"] == "gnome-ai-panel"


async def test_thinking(backends, work) -> None:
    backend = backends(fake_agent(work, "thinking"))
    session = await backend.new_session()
    events = await collect(backend, session, "hej")
    assert text_of(events, ThinkingDelta) == "Zastanawiam się nad odpowiedzią."
    assert text_of(events) == "Echo: hej"
    first_text = next(i for i, e in enumerate(events) if isinstance(e, TextDelta))
    assert all(isinstance(e, ThinkingDelta) for e in events[:first_text])
    assert events[-1] == Done("end_turn")


async def test_tool_call_and_two_updates(backends, work) -> None:
    backend = backends(fake_agent(work, "tool"))
    session = await backend.new_session()
    events = await collect(backend, session, "x")
    calls = [e for e in events if isinstance(e, ToolCall)]
    updates = [e for e in events if isinstance(e, ToolUpdate)]
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].title == "Odczyt pliku notes.txt"
    assert calls[0].kind == "read"
    assert calls[0].status == "pending"
    assert calls[0].raw_input == {"path": "notes.txt"}
    assert [u.status for u in updates] == ["in_progress", "completed"]
    assert all(u.id == "call_1" for u in updates)
    assert updates[1].content[0]["content"]["text"] == "zawartość"
    assert text_of(events, ThinkingDelta) == "Sprawdzę plik."
    assert events[-1] == Done("end_turn")


async def test_usage_update(backends, work) -> None:
    backend = backends(fake_agent(work, "usage"))
    session = await backend.new_session()
    events = await collect(backend, session, "x")
    assert Usage(used=1234, size=200000, cost_amount=0.0123, cost_currency="USD") in events


async def test_noise_on_stdout_is_ignored(backends, work) -> None:
    backend = backends(fake_agent(work, "noise"))
    session = await backend.new_session()
    events = await collect(backend, session, "abc")
    assert text_of(events) == "Echo: abc"
    assert events[-1] == Done("end_turn")


# -- permissions -------------------------------------------------------------------------------


async def run_permission(backend: AcpBackend, answer: Callable[[PermissionRequest], str | None]):
    session = await backend.new_session()
    requests: list[PermissionRequest] = []

    async def on_event(event) -> None:
        if isinstance(event, PermissionRequest):
            requests.append(event)
            backend.respond_permission(event.request_id, answer(event))

    events = await collect(backend, session, "zrób", on_event)
    return events, requests


async def test_permission_allow_completes_the_tool(backends, work) -> None:
    backend = backends(fake_agent(work, "permission"))
    events, requests = await run_permission(backend, lambda r: "allow")
    assert len(requests) == 1
    request = requests[0]
    assert request.tool_call_id == "call_perm"
    assert request.title == "Zapis pliku out.txt"
    assert request.kind == "edit"
    assert request.raw_input == {"path": "out.txt", "content": "x"}
    assert [(o.id, o.kind) for o in request.options] == [
        ("allow", "allow_once"),
        ("reject", "reject_once"),
    ]
    updates = [e for e in events if isinstance(e, ToolUpdate)]
    assert updates[-1].status == "completed"
    assert text_of(events) == "Zezwolono"
    assert events[-1] == Done("end_turn")


@pytest.mark.parametrize("answer", ["reject", None, "no-such-option"])
async def test_permission_reject_fails_the_tool(backends, work, answer) -> None:
    backend = backends(fake_agent(work, "permission"))
    events, _ = await run_permission(backend, lambda r: answer)
    updates = [e for e in events if isinstance(e, ToolUpdate)]
    assert updates[-1].status == "failed"
    assert text_of(events) == "Odmowa"
    assert events[-1] == Done("end_turn")


async def test_cancel_with_open_permission_request(backends, work) -> None:
    backend = backends(fake_agent(work, "permission"))
    session = await backend.new_session()

    async def on_event(event) -> None:
        if isinstance(event, PermissionRequest):
            await backend.cancel(session)

    events = await collect(backend, session, "zrób", on_event)
    assert events[-1] == Done("cancelled")
    assert [e.status for e in events if isinstance(e, ToolUpdate)] == ["failed"]


async def test_respond_to_unknown_permission_is_ignored(backends, work) -> None:
    backend = backends(fake_agent(work, "echo"))
    backend.respond_permission("perm-404", "allow")


# -- cancel --------------------------------------------------------------------------------------


async def test_slow_cancel_ends_with_cancelled_within_2_s(backends, work) -> None:
    backend = backends(fake_agent(work, "slow"))
    session = await backend.new_session()
    events = []
    cancelled_at = None
    async with asyncio.timeout(15):
        async for event in backend.send(session, [{"type": "text", "text": "długo"}]):
            events.append(event)
            if cancelled_at is None and len(events) >= 2:
                cancelled_at = time.monotonic()
                await backend.cancel(session)
    assert events[-1] == Done("cancelled")
    assert time.monotonic() - cancelled_at <= 2.0
    # The session keeps working after a cancelled turn.
    backend2_events = await collect_first_text(backend, session)
    assert backend2_events.startswith("fragment 1")
    await backend.cancel(session)


async def collect_first_text(backend: AcpBackend, session: str) -> str:
    async with asyncio.timeout(10):
        stream = backend.send(session, [{"type": "text", "text": "znowu"}])
        try:
            async for event in stream:
                if isinstance(event, TextDelta):
                    return event.text
        finally:
            await stream.aclose()
    return ""


async def test_closing_the_stream_early_cancels_the_turn(backends, work, tmp_path) -> None:
    backend = backends(fake_agent(work, "slow"))
    session = await backend.new_session()
    assert (await collect_first_text(backend, session)).startswith("fragment")
    # The agent got session/cancel, so the next turn of the same session can start.
    events = []
    async with asyncio.timeout(10):
        async for event in backend.send(session, [{"type": "text", "text": "x"}]):
            events.append(event)
            if len(events) == 1:
                await backend.cancel(session)
    assert events[-1] == Done("cancelled")


async def test_cancel_without_turn_is_a_no_op(backends, work) -> None:
    backend = backends(fake_agent(work, "echo"))
    session = await backend.new_session()
    await backend.cancel(session)
    await backend.cancel("sess_unknown")
    assert text_of(await collect(backend, session, "a")) == "Echo: a"


# -- sessions ------------------------------------------------------------------------------------


async def test_two_parallel_sessions_in_one_process(backends, work) -> None:
    backend = backends(fake_agent(work, "echo"))
    first = await backend.new_session()
    pid = backend.pid
    second = await backend.new_session()
    assert first != second
    assert backend.pid == pid
    a, b = await asyncio.gather(
        collect(backend, first, "pierwsza"), collect(backend, second, "druga")
    )
    assert text_of(a) == "Echo: pierwsza"
    assert text_of(b) == "Echo: druga"
    assert a[-1] == b[-1] == Done("end_turn")


async def test_two_parallel_slow_turns_are_routed_by_session(backends, work) -> None:
    backend = backends(fake_agent(work, "slow"))
    first = await backend.new_session()
    second = await backend.new_session()

    async def turn(session: str) -> list:
        events = []
        async for event in backend.send(session, [{"type": "text", "text": "x"}]):
            events.append(event)
            if len(events) == 3:
                await backend.cancel(session)
        return events

    async with asyncio.timeout(10):
        a, b = await asyncio.gather(turn(first), turn(second))
    for events in (a, b):
        texts = [e.text for e in events if isinstance(e, TextDelta)]
        assert texts[:3] == ["fragment 1 ", "fragment 2 ", "fragment 3 "]
        assert events[-1] == Done("cancelled")


async def test_second_turn_in_the_same_session_while_one_runs(backends, work) -> None:
    backend = backends(fake_agent(work, "slow"))
    session = await backend.new_session()
    stream = backend.send(session, [{"type": "text", "text": "x"}])
    assert isinstance(await anext(stream), TextDelta)
    events = await collect(backend, session, "y")
    assert events == [Error("W tej sesji trwa już tura", "other")]
    await backend.cancel(session)
    async for _ in stream:
        pass


async def test_unknown_session(backends, work) -> None:
    backend = backends(fake_agent(work, "echo"))
    events = await collect(backend, "sess_404", "x")
    assert len(events) == 1
    assert isinstance(events[0], Error)
    assert events[0].kind == "other"


async def test_session_new_params_mcp_meta_cwd(backends, work, tmp_path) -> None:
    rec = tmp_path / "rec.jsonl"
    mcp = {
        "files": McpServer(
            id="files",
            command="/usr/bin/env",
            args=["mcp-files", "--root", "data"],
            env={"FILES_TOKEN": Literal("tok-12345"), "MODE": Literal("ro")},
        ),
        "unused": McpServer(id="unused", command="/bin/true"),
    }
    agent = fake_agent(
        work,
        "echo",
        "--record",
        str(rec),
        mcp=["files"],
        session_meta={"claudeCode": {"options": {"disallowedTools": ["Bash"]}}},
        system_prompt="Bądź zwięzły.",
    )
    backend = backends(agent, mcp)
    await backend.new_session()
    new = next(r for r in records(rec) if r["method"] == "session/new")["params"]
    assert new["cwd"] == str(work)
    assert os.path.isabs(new["cwd"])
    assert new["mcpServers"] == [
        {
            "name": "files",
            "command": "/usr/bin/env",
            "args": ["mcp-files", "--root", "data"],
            "env": [{"name": "FILES_TOKEN", "value": "tok-12345"}, {"name": "MODE", "value": "ro"}],
        }
    ]
    assert new["_meta"] == {"claudeCode": {"options": {"disallowedTools": ["Bash"]}}}
    # The fake agent does not advertise sessionCapabilities.systemPrompt.
    assert "systemPrompt" not in new


async def test_system_prompt_sent_when_advertised(backends, work, tmp_path) -> None:
    rec = tmp_path / "rec.jsonl"
    agent = fake_agent(
        work, "echo", "--record", str(rec), "--system-prompt", system_prompt="Bądź zwięzły."
    )
    backend = backends(agent)
    await backend.new_session()
    new = next(r for r in records(rec) if r["method"] == "session/new")["params"]
    assert new["systemPrompt"] == {
        "mode": "append",
        "content": [{"type": "text", "text": "Bądź zwięzły."}],
    }
    assert new["mcpServers"] == []
    assert "_meta" not in new


async def test_mcp_env_is_redacted_in_debug_log(backends, work, caplog) -> None:
    mcp = {"m": McpServer(id="m", command="/bin/true", env={"API_TOKEN": Literal("tok-abcdef")})}
    backend = backends(fake_agent(work, "echo", mcp=["m"]), mcp)
    with caplog.at_level(logging.DEBUG, logger="app"):
        await backend.new_session()
    assert "session/new" in caplog.text
    assert "tok-abcdef" not in caplog.text


async def test_secret_from_env_reaches_the_agent_process(backends, work, caplog) -> None:
    agent = fake_agent(work, "env", env={"SECRET_VAR": Command(cmd="printf s3cr3t-value")})
    backend = backends(agent)
    session = await backend.new_session()
    with caplog.at_level(logging.DEBUG, logger="app"):
        events = await collect(backend, session, "SECRET_VAR")
    assert text_of(events) == "s3cr3t-value"


# -- failures ------------------------------------------------------------------------------------


async def test_bad_version_is_a_protocol_error(backends, work) -> None:
    backend = backends(fake_agent(work, "bad-version"))
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "protocol"
    assert "99" in info.value.event.message
    assert backend.pid is None


async def test_auth_required_lists_auth_methods(backends, work) -> None:
    backend = backends(fake_agent(work, "auth"))
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    error = info.value.event
    assert error.kind == "auth"
    assert error.auth_methods[0]["id"] == "fake-login"
    assert "Fake login" in error.message


@pytest.mark.parametrize("command", ["/nonexistent/agent", "no-such-agent-command-xyz"])
async def test_missing_command_is_a_spawn_error(backends, work, command) -> None:
    agent = AcpAgent(id="missing", name="Missing", command=command, cwd=work)
    backend = backends(agent)
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "spawn"
    assert info.value.event.message == f"Nie znaleziono polecenia: {command}"


async def test_not_executable_command_is_a_spawn_error(backends, work, tmp_path) -> None:
    script = tmp_path / "agent.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o600)
    backend = backends(AcpAgent(id="noexec", name="x", command=str(script), cwd=work))
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "spawn"
    assert str(script) in info.value.event.message


async def test_startup_timeout_kills_the_process(backends, work) -> None:
    agent = AcpAgent(id="sleepy", name="x", command="sleep", args=["30"], cwd=work)
    agent.startup_timeout_s = 1
    backend = backends(agent)
    started = time.monotonic()
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "timeout"
    assert "1 s" in info.value.event.message
    assert time.monotonic() - started < 4
    assert backend.pid is None


async def test_failing_secret_command_is_a_spawn_error(backends, work) -> None:
    agent = fake_agent(work, "echo", env={"TOKEN": Command(cmd="false")})
    backend = backends(agent)
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "spawn"
    assert "TOKEN" in info.value.event.message


async def test_agent_exiting_at_start(backends, work) -> None:
    agent = AcpAgent(
        id="exits",
        name="x",
        command=sys.executable,
        args=["-c", "import sys; sys.stderr.write('no config\\n'); sys.exit(4)"],
        cwd=work,
    )
    backend = backends(agent)
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "crashed"
    assert "4" in info.value.event.message
    assert "no config" in info.value.event.message


async def test_crash_during_turn_then_restart(backends, work) -> None:
    backend = backends(fake_agent(work, "crash"))
    session = await backend.new_session()
    first_pid = backend.pid
    events = await collect(backend, session, "a")
    error = events[-1]
    assert isinstance(error, Error)
    assert error.kind == "crashed"
    assert "boom" in error.message
    assert "3" in error.message
    assert error.stderr == "boom"
    # The old session is gone ...
    lost = await collect(backend, session, "b")
    assert lost[-1].kind == "crashed"
    # ... and the next session starts a new process.
    new_session = await backend.new_session()
    assert backend.pid not in (None, first_pid)
    assert new_session


async def test_crash_once_next_session_works(backends, work) -> None:
    backend = backends(fake_agent(work, "crash-once"))
    session = await backend.new_session()
    events = await collect(backend, session, "a")
    assert events[-1].kind == "crashed"
    session = await backend.new_session()
    events = await collect(backend, session, "b")
    assert text_of(events) == "Echo: b"
    assert events[-1] == Done("end_turn")


async def test_restart_limit(backends, work) -> None:
    backend = backends(fake_agent(work, "crash"))
    for _ in range(1 + acp_module.RESTART_LIMIT):  # first start + allowed restarts
        session = await backend.new_session()
        events = await collect(backend, session, "a")
        assert events[-1].kind == "crashed"
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "crashed"
    assert "zbyt często" in info.value.event.message


async def test_restart_limit_window(backends, work, monkeypatch) -> None:
    monkeypatch.setattr(acp_module, "RESTART_WINDOW_S", 0.0)
    backend = backends(fake_agent(work, "crash"))
    for _ in range(2 + acp_module.RESTART_LIMIT):
        session = await backend.new_session()
        events = await collect(backend, session, "a")
        assert events[-1].kind == "crashed"


# -- close -------------------------------------------------------------------------------------


async def test_close_stops_the_process(backends, work) -> None:
    backend = backends(fake_agent(work, "echo"))
    await backend.new_session()
    pid = backend.pid
    await backend.close()
    assert process_gone(pid)
    await backend.close()  # safe twice
    with pytest.raises(BackendError):
        await backend.new_session()


async def test_close_kills_an_agent_ignoring_sigterm(backends, work, monkeypatch) -> None:
    monkeypatch.setattr(acp_module, "TERM_GRACE_S", 0.5)
    code = (
        "import runpy, signal, sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"sys.argv = [{str(FAKE)!r}, '--scenario', 'echo']; "
        f"runpy.run_path({str(FAKE)!r}, run_name='__main__')"
    )
    agent = AcpAgent(id="stubborn", name="x", command=sys.executable, args=["-c", code], cwd=work)
    backend = backends(agent)
    await backend.new_session()
    pid = backend.pid
    started = time.monotonic()
    await backend.close()
    assert process_gone(pid)
    assert time.monotonic() - started < 3


async def test_close_during_turn_ends_it(backends, work) -> None:
    backend = backends(fake_agent(work, "slow"))
    session = await backend.new_session()
    events = []
    async with asyncio.timeout(10):
        async for event in backend.send(session, [{"type": "text", "text": "x"}]):
            events.append(event)
            if len(events) == 1:
                await backend.close()
    assert isinstance(events[-1], Error)
    assert events[-1].kind == "other"


# -- registry ----------------------------------------------------------------------------------


async def test_get_backend_one_process_per_agent(work) -> None:
    try:
        agent = fake_agent(work, "echo")
        backend = get_backend(agent)
        assert get_backend(fake_agent(work, "echo")) is backend
        other = get_backend(fake_agent(work, "echo", id="fake-other"))
        assert other is not backend
        await backend.new_session()
        pid = backend.pid
        await backend.new_session()
        assert backend.pid == pid
    finally:
        await close_all()
    assert process_gone(pid)


async def test_changed_config_restarts_at_next_session(work, tmp_path) -> None:
    try:
        backend = get_backend(fake_agent(work, "echo"))
        await backend.new_session()
        pid = backend.pid
        changed = fake_agent(work, "thinking", id="fake-echo", name="Zmieniony")
        assert get_backend(changed) is backend
        assert backend.pid == pid  # nothing happens before the next session
        session = await backend.new_session()
        assert backend.pid != pid
        assert backend.name == "Zmieniony"
        events = await collect(backend, session, "x")
        assert text_of(events, ThinkingDelta)
    finally:
        await close_all()
