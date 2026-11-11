"""Tester additions for S2-T5 attempt 2: regressions of the ``--cancel-after 0`` race.

Covers the CLI side (timer started before the turn was registered) and the fake agent side
(cancel flag reset when the prompt task started instead of when the prompt was read).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "tests" / "data" / "config_fake.toml"
FAKE = REPO / "tests" / "fakes" / "fake_acp_agent.py"


def cli(*args: str, debug: bool = False) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["AI_PANEL_CONFIG"] = str(CONFIG)
    env.pop("AI_PANEL_LOG_LEVEL", None)
    if debug:
        env["AI_PANEL_LOG_LEVEL"] = "DEBUG"
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def agents_under(root: Path) -> list[str]:
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cwd = Path(os.readlink(proc / "cwd"))
        except OSError:
            continue
        if cwd == root or root in cwd.parents:
            found.append(proc.name)
    return found


@pytest.mark.parametrize("debug", [False, True])
def test_cancel_after_zero_is_reliable(isolated_env, debug: bool) -> None:
    # The race depended on timing (DEBUG logging hid it), so repeat it in both modes.
    for _ in range(5):
        started = time.monotonic()
        result = cli("chat", "fake-slow", "x", "--json", "--cancel-after", "0", debug=debug)
        assert result.returncode == 0, result.stderr
        events = [json.loads(line) for line in result.stdout.splitlines()]
        assert events[-1] == {"type": "done", "stop_reason": "cancelled"}
        assert time.monotonic() - started < 5, "turn was not cancelled promptly"


def test_cancel_after_zero_text_mode(isolated_env) -> None:
    result = cli("chat", "fake-slow", "x", "--cancel-after", "0")
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip().endswith("[done] cancelled")


def test_cancel_after_zero_with_pending_permission(isolated_env) -> None:
    # The permission request of a cancelled turn must not hang the CLI or leave the agent.
    result = cli("chat", "fake-perm", "x", "--json", "--cancel-after", "0")
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1] == {"type": "done", "stop_reason": "cancelled"}
    root = isolated_env["HOME"] / ".cache" / "gnome-ai-panel-fake"
    deadline = time.monotonic() + 3
    while agents_under(root) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert agents_under(root) == []


def _rpc(id_: int | None, method: str, params: dict) -> str:
    msg = {"jsonrpc": "2.0", "method": method, "params": params}
    if id_ is not None:
        msg["id"] = id_
    return json.dumps(msg) + "\n"


def _run_fake(scenario: str, cwd: Path, lines_after_session: list[str]) -> list[dict]:
    """Drive the fake agent: initialize, session/new, then the given lines in one write."""
    proc = subprocess.Popen(
        [sys.executable, str(FAKE), "--scenario", scenario],
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        proc.stdin.write(_rpc(0, "initialize", {"protocolVersion": 1}))
        proc.stdin.write(_rpc(1, "session/new", {"cwd": str(cwd), "mcpServers": []}))
        proc.stdin.flush()
        out = []
        session_id = None
        while session_id is None:
            msg = json.loads(proc.stdout.readline())
            if msg.get("id") == 1:
                session_id = msg["result"]["sessionId"]
        proc.stdin.write("".join(line.replace("SID", session_id) for line in lines_after_session))
        proc.stdin.flush()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            msg = json.loads(line)
            out.append(msg)
            if msg.get("id") == 2:
                break
        return out
    finally:
        proc.kill()
        proc.wait(timeout=5)


def _stop_reason(messages: list[dict]) -> str:
    reply = next(m for m in messages if m.get("id") == 2)
    return reply["result"]["stopReason"]


def test_fake_agent_cancel_in_same_write_as_prompt_cancels_it(tmp_path) -> None:
    lines = [
        _rpc(2, "session/prompt", {"sessionId": "SID", "prompt": [{"type": "text", "text": "x"}]}),
        _rpc(None, "session/cancel", {"sessionId": "SID"}),
    ]
    started = time.monotonic()
    assert _stop_reason(_run_fake("slow", tmp_path, lines)) == "cancelled"
    assert time.monotonic() - started < 5


def test_fake_agent_cancel_before_prompt_does_not_leak(tmp_path) -> None:
    # A cancel with no running turn must not cancel the next prompt.
    lines = [
        _rpc(None, "session/cancel", {"sessionId": "SID"}),
        _rpc(2, "session/prompt", {"sessionId": "SID", "prompt": [{"type": "text", "text": "x"}]}),
    ]
    assert _stop_reason(_run_fake("echo", tmp_path, lines)) == "end_turn"
