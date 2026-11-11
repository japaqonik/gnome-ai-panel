"""Tester additions for S2-T5: Ctrl+C, leftover agent processes, secret leaks.

The CLI runs as a subprocess against tests/data/config_fake.toml with HOME/XDG_* from
``isolated_env``; an agent "belongs" to a test when its cwd is under the isolated
``~/.cache/gnome-ai-panel-fake``.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "tests" / "data" / "config_fake.toml"
SECRET = "s3cr3t-value"


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["AI_PANEL_CONFIG"] = str(CONFIG)
    env.pop("AI_PANEL_LOG_LEVEL", None)
    env.update(extra or {})
    return env


def cli(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=REPO,
        env=_env(env_extra),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def agents_under(root: Path) -> list[str]:
    """PIDs of processes whose cwd is ``root`` or below it."""
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


def wait_no_agents(root: Path, timeout: float = 3.0) -> list[str]:
    deadline = time.monotonic() + timeout
    left = agents_under(root)
    while left and time.monotonic() < deadline:
        time.sleep(0.05)
        left = agents_under(root)
    return left


def fake_root(isolated_env) -> Path:
    return isolated_env["HOME"] / ".cache" / "gnome-ai-panel-fake"


@pytest.mark.parametrize("json_mode", [False, True])
def test_ctrl_c_during_chat_exits_130_and_stops_agent(isolated_env, json_mode: bool) -> None:
    args = [sys.executable, "-m", "app.cli", "chat", "fake-slow", "długo"]
    if json_mode:
        args.append("--json")
    proc = subprocess.Popen(
        args,
        cwd=REPO,
        env=_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Wait for the first streamed bytes (text mode has no newline until the turn ends).
        first = os.read(proc.stdout.fileno(), 4096).decode()
        assert first, proc.stderr.read()
        assert agents_under(fake_root(isolated_env)), "agent should be running"
        proc.send_signal(signal.SIGINT)
        out_b, err_b = proc.communicate(timeout=15)
        out, err = out_b.decode(), err_b.decode()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 130, err
    assert "Traceback" not in err
    assert "przerwano" in err
    if json_mode:
        for line in (first + out).splitlines():
            json.loads(line)
    assert wait_no_agents(fake_root(isolated_env)) == []


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (("chat", "fake-echo", "x"), 0),
        (("chat", "fake-crash", "x"), 2),
        (("chat", "fake-auth", "x"), 2),
        (("chat", "fake-badver", "x"), 2),
        (("chat", "fake-slow", "x", "--cancel-after", "0.3"), 0),
        (("chat", "fake-perm", "x"), 0),
        (("test-agent", "fake-auth"), 2),
        (("test-agent", "fake-badver"), 2),
        (("test-agent", "fake-crash"), 0),
    ],
)
def test_no_agent_process_left_after_cli(isolated_env, args: tuple[str, ...], code: int) -> None:
    result = cli(*args)
    assert result.returncode == code, result.stdout + result.stderr
    assert wait_no_agents(fake_root(isolated_env)) == []


def test_secret_not_in_log_at_default_level(isolated_env) -> None:
    result = cli("chat", "fake-env", "SECRET_VAR")
    assert result.returncode == 0, result.stderr
    assert SECRET in result.stdout
    assert SECRET not in result.stderr
    log_dir = isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel"
    for path in log_dir.glob("app.log*"):
        assert SECRET not in path.read_text(encoding="utf-8")


def test_secret_json_mode_and_test_agent_do_not_log_it(isolated_env) -> None:
    debug = {"AI_PANEL_LOG_LEVEL": "DEBUG"}
    chat = cli("chat", "fake-env", "SECRET_VAR", "--json", env_extra=debug)
    assert chat.returncode == 0, chat.stderr
    text = "".join(e.get("text", "") for e in map(json.loads, chat.stdout.splitlines()))
    assert SECRET in text
    assert SECRET not in chat.stderr
    test = cli("test-agent", "fake-env", env_extra=debug)
    assert test.returncode == 0, test.stdout + test.stderr
    assert SECRET not in test.stdout + test.stderr
    log_dir = isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel"
    logs = list(log_dir.glob("app.log*"))
    assert logs
    for path in logs:
        assert SECRET not in path.read_text(encoding="utf-8")
    assert wait_no_agents(fake_root(isolated_env)) == []


def test_cancel_after_zero_cancels_immediately(isolated_env) -> None:
    # "--cancel-after 0" is accepted by the parser, so it must cancel the turn (not be ignored).
    result = cli("chat", "fake-slow", "x", "--json", "--cancel-after", "0")
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1] == {"type": "done", "stop_reason": "cancelled"}


def test_cancel_after_longer_than_turn_is_harmless(isolated_env) -> None:
    result = cli("chat", "fake-echo", "x", "--json", "--cancel-after", "30")
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1] == {"type": "done", "stop_reason": "end_turn"}


def test_chat_missing_prompt_is_usage_error(isolated_env) -> None:
    result = cli("chat", "fake-echo")
    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert agents_under(fake_root(isolated_env)) == []


def test_unicode_and_multiline_prompt(isolated_env) -> None:
    result = cli("chat", "fake-echo", "zażółć\ngęślą")
    assert result.returncode == 0, result.stderr
    assert "zażółć" in result.stdout and "gęślą" in result.stdout
