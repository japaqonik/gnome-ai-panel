"""Extra AcpBackend edge cases added by the tester (S2-T4): no agent process may survive a
failure path, process-group cleanup, stderr tail limit, idle crash, relative cwd."""

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest

from app.backends import acp as acp_module
from app.backends.acp import AcpBackend
from app.backends.base import BackendError, Done, Error, PermissionRequest, TextDelta
from app.config import AcpAgent

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


def process_gone(pid: int) -> bool:
    """True when ``pid`` no longer exists or is only a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ", 1)[1].startswith("Z")
    except (FileNotFoundError, ProcessLookupError):
        # Reading /proc/<pid>/stat of a process reaped in the meantime fails with ESRCH.
        return True


async def wait_gone(pid: int, timeout: float = 3.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if process_gone(pid):
            return True
        await asyncio.sleep(0.05)
    return process_gone(pid)


@pytest.fixture
def work(isolated_env, tmp_path: Path) -> Path:
    return tmp_path / "work" / "agent"


@pytest.fixture
def spawned(monkeypatch) -> list[int]:
    """PIDs of every process AcpBackend starts (also those that fail during start)."""
    pids: list[int] = []
    original = asyncio.create_subprocess_exec

    async def wrapper(*args, **kwargs):
        proc = await original(*args, **kwargs)
        pids.append(proc.pid)
        return proc

    monkeypatch.setattr(acp_module.asyncio, "create_subprocess_exec", wrapper)
    return pids


async def collect(backend: AcpBackend, session_id: str, text: str) -> list:
    events = []
    async with asyncio.timeout(15):
        async for event in backend.send(session_id, [{"type": "text", "text": text}]):
            events.append(event)
    return events


async def test_startup_timeout_leaves_no_process(work, spawned) -> None:
    agent = AcpAgent(id="sleepy", name="x", command="sleep", args=["30"], cwd=work)
    agent.startup_timeout_s = 1
    backend = AcpBackend(agent)
    try:
        with pytest.raises(BackendError) as info:
            await backend.new_session()
        assert info.value.kind == "timeout"
        assert len(spawned) == 1
        assert await wait_gone(spawned[0])
    finally:
        await backend.close()


@pytest.mark.parametrize("scenario", ["bad-version"])
async def test_failed_initialize_leaves_no_process(work, spawned, scenario) -> None:
    backend = AcpBackend(fake_agent(work, scenario))
    try:
        with pytest.raises(BackendError):
            await backend.new_session()
        assert len(spawned) == 1
        assert await wait_gone(spawned[0])
    finally:
        await backend.close()


async def test_auth_error_then_close_leaves_no_process(work, spawned) -> None:
    backend = AcpBackend(fake_agent(work, "auth"))
    with pytest.raises(BackendError) as info:
        await backend.new_session()
    assert info.value.kind == "auth"
    await backend.close()
    assert spawned and all([await wait_gone(pid) for pid in spawned])


async def test_crashed_and_restarted_processes_are_all_reaped(work, spawned) -> None:
    backend = AcpBackend(fake_agent(work, "crash"))
    try:
        for _ in range(2):
            session = await backend.new_session()
            events = await collect(backend, session, "a")
            assert events[-1].kind == "crashed"
        assert len(spawned) == 2
    finally:
        await backend.close()
    for pid in spawned:
        assert await wait_gone(pid)


async def test_close_kills_children_in_the_process_group(work, tmp_path) -> None:
    pidfile = tmp_path / "child.pid"
    code = (
        "import runpy, subprocess, sys; "
        "p = subprocess.Popen(['sleep', '30'], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        f"open({str(pidfile)!r}, 'w').write(str(p.pid)); "
        f"sys.argv = [{str(FAKE)!r}, '--scenario', 'echo']; "
        f"runpy.run_path({str(FAKE)!r}, run_name='__main__')"
    )
    agent = AcpAgent(id="parent", name="x", command=sys.executable, args=["-c", code], cwd=work)
    backend = AcpBackend(agent)
    await backend.new_session()
    child = int(pidfile.read_text())
    assert not process_gone(child)
    await backend.close()
    assert await wait_gone(child)


async def test_stderr_tail_is_limited_to_20_lines(work) -> None:
    code = (
        "import sys\n"
        "for i in range(1, 31): sys.stderr.write(f'line-{i:02d}\\n')\n"
        "sys.stderr.flush(); sys.exit(5)\n"
    )
    agent = AcpAgent(id="noisy", name="x", command=sys.executable, args=["-c", code], cwd=work)
    backend = AcpBackend(agent)
    try:
        with pytest.raises(BackendError) as info:
            await backend.new_session()
        error = info.value.event
        assert error.kind == "crashed"
        lines = error.stderr.splitlines()
        assert lines == [f"line-{i:02d}" for i in range(11, 31)]
        assert "line-10" not in error.message
        assert "line-30" in error.message
    finally:
        await backend.close()


async def test_agent_killed_while_idle_restarts_at_next_session(work) -> None:
    backend = AcpBackend(fake_agent(work, "echo"))
    try:
        session = await backend.new_session()
        pid = backend.pid
        os.kill(pid, signal.SIGKILL)
        assert await wait_gone(pid)
        await asyncio.sleep(0.2)
        events = await collect(backend, session, "x")
        assert len(events) == 1
        assert isinstance(events[0], Error)
        assert events[0].kind == "crashed"
        session = await backend.new_session()
        assert backend.pid not in (None, pid)
        events = await collect(backend, session, "y")
        assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Echo: y"
        assert events[-1] == Done("end_turn")
    finally:
        await backend.close()


async def test_close_with_open_permission_request_ends_the_turn(work) -> None:
    backend = AcpBackend(fake_agent(work, "permission"))
    session = await backend.new_session()
    pid = backend.pid
    events = []
    async with asyncio.timeout(10):
        async for event in backend.send(session, [{"type": "text", "text": "zrób"}]):
            events.append(event)
            if isinstance(event, PermissionRequest):
                await backend.close()
    assert isinstance(events[-1], Error | Done)
    assert await wait_gone(pid)


async def test_relative_cwd_is_sent_absolute(isolated_env, tmp_path, monkeypatch) -> None:
    import json

    monkeypatch.chdir(tmp_path)
    rec = tmp_path / "rec.jsonl"
    backend = AcpBackend(fake_agent(Path("rel/agent"), "echo", "--record", str(rec)))
    try:
        await backend.new_session()
        new = next(
            json.loads(line)
            for line in rec.read_text().splitlines()
            if json.loads(line)["method"] == "session/new"
        )
        assert new["params"]["cwd"] == str(tmp_path / "rel" / "agent")
        assert (tmp_path / "rel" / "agent").is_dir()
    finally:
        await backend.close()
