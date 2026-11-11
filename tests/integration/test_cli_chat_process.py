"""CLI ``chat`` and ``test-agent`` as subprocesses against tests/data/config_fake.toml (S2-T5).

Every agent of the file is exercised. HOME/XDG_* come from ``isolated_env`` (the agents'
``cwd`` is ``~/.cache/…`` and the log goes to ``$XDG_STATE_HOME``).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import load_config

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "tests" / "data" / "config_fake.toml"
TIMEOUT = 60


def cli(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["AI_PANEL_CONFIG"] = str(CONFIG)
    env.pop("AI_PANEL_LOG_LEVEL", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=REPO,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def json_lines(stdout: str) -> list[dict]:
    lines = stdout.splitlines()
    assert lines, "no output"
    return [json.loads(line) for line in lines]


def assert_no_traceback(result: subprocess.CompletedProcess[str]) -> None:
    assert "Traceback" not in result.stdout + result.stderr


# Expected result of `chat <id> 'Cześć'` for every agent of config_fake.toml.
CHAT_CASES = {
    "fake-echo": (0, ["Echo: Cześć"]),
    "fake-thinking": (0, ["[thinking] ", "Echo: Cześć"]),
    "fake-tool": (0, ["[thinking] ", "[tool] ", "completed"]),
    "fake-perm": (0, ["[permission] ", "odrzucono", "Odmowa"]),
    "fake-crash": (2, ["kod 3", "boom"]),
    "fake-crash-once": (2, ["kod 3", "boom"]),  # first prompt in a fresh cwd crashes
    "fake-badver": (2, ["Nieobsługiwana wersja protokołu"]),
    "fake-auth": (2, ["wymaga zalogowania", "Fake login"]),
    "fake-noise": (0, ["Echo: Cześć"]),
    "fake-models": (0, ["[fake-small] Echo: Cześć"]),
    "fake-load": (0, ["Echo: Cześć"]),
    "fake-usage": (0, ["Echo: Cześć", "[usage] "]),
    "fake-image": (0, ["Echo: Cześć"]),
    "fake-env": (0, []),
    "fake-missing": (2, ["Nie znaleziono polecenia"]),
}


def test_cases_cover_every_configured_agent() -> None:
    config = load_config(CONFIG)
    assert not config.errors
    assert config.default_agent == "fake-echo"
    # fake-slow is covered by the cancel tests below.
    assert set(config.agents) == set(CHAT_CASES) | {"fake-slow"}


@pytest.mark.parametrize("agent_id", sorted(CHAT_CASES))
def test_chat_every_agent(isolated_env, agent_id: str) -> None:
    code, needles = CHAT_CASES[agent_id]
    result = cli("chat", agent_id, "Cześć")
    output = result.stdout + result.stderr
    assert result.returncode == code, output
    for needle in needles:
        assert needle in output, output
    assert_no_traceback(result)
    if code == 2:
        assert result.stderr.startswith("błąd: ")


@pytest.mark.parametrize("agent_id", sorted(CHAT_CASES))
def test_chat_json_every_agent(isolated_env, agent_id: str) -> None:
    code, _ = CHAT_CASES[agent_id]
    result = cli("chat", agent_id, "Cześć", "--json")
    assert result.returncode == code, result.stdout + result.stderr
    events = json_lines(result.stdout)
    assert all(isinstance(e, dict) and isinstance(e.get("type"), str) for e in events)
    last = events[-1]
    if code == 0:
        assert last["type"] == "done"
        assert last["stop_reason"] == "end_turn"
    else:
        assert last["type"] == "error"
        assert last["message"]
    assert_no_traceback(result)


def test_chat_echo_json_stream(isolated_env) -> None:
    events = json_lines(cli("chat", "fake-echo", "Cześć", "--json").stdout)
    deltas = [e["text"] for e in events if e["type"] == "text_delta"]
    assert len(deltas) == 3
    assert "".join(deltas) == "Echo: Cześć"
    assert events[-1] == {"type": "done", "stop_reason": "end_turn"}


def test_chat_permission_deny_is_default(isolated_env) -> None:
    events = json_lines(cli("chat", "fake-perm", "zapisz", "--json").stdout)
    request = next(e for e in events if e["type"] == "permission_request")
    response = next(e for e in events if e["type"] == "permission_response")
    assert response == {
        "type": "permission_response",
        "request_id": request["request_id"],
        "option_id": None,
        "allowed": False,
    }
    text = "".join(e["text"] for e in events if e["type"] == "text_delta")
    assert "Odmowa" in text and "Zezwolono" not in text


def test_chat_permission_explicit_deny_and_allow(isolated_env) -> None:
    denied = cli("chat", "fake-perm", "zapisz", "--permission", "deny")
    assert denied.returncode == 0
    assert "Odmowa" in denied.stdout
    allowed = cli("chat", "fake-perm", "zapisz", "--permission", "allow")
    assert allowed.returncode == 0, allowed.stderr
    assert "[permission] " in allowed.stdout and "zezwolono" in allowed.stdout
    assert "Zezwolono" in allowed.stdout and "Odmowa" not in allowed.stdout


def test_chat_cancel_after_on_slow(isolated_env) -> None:
    result = cli("chat", "fake-slow", "długo", "--json", "--cancel-after", "0.5")
    assert result.returncode == 0, result.stderr
    events = json_lines(result.stdout)
    assert events[-1] == {"type": "done", "stop_reason": "cancelled"}
    # 200 ms per fragment: far fewer than the 50 of a full 10 s turn.
    assert 1 <= sum(e["type"] == "text_delta" for e in events) < 10


def test_chat_cancel_after_text_mode(isolated_env) -> None:
    result = cli("chat", "fake-slow", "długo", "--cancel-after", "0.3")
    assert result.returncode == 0, result.stderr
    assert result.stdout.rstrip().endswith("[done] cancelled")


@pytest.mark.parametrize("value", ["-1", "abc", "nan", "inf"])
def test_chat_cancel_after_rejects_bad_values(isolated_env, value: str) -> None:
    result = cli("chat", "fake-echo", "x", "--cancel-after", value)
    assert result.returncode == 2
    assert "nieujemnej liczby sekund" in result.stderr


def test_chat_env_secret_reaches_agent_but_not_log(isolated_env) -> None:
    result = cli("chat", "fake-env", "SECRET_VAR", env_extra={"AI_PANEL_LOG_LEVEL": "DEBUG"})
    assert result.returncode == 0, result.stderr
    assert "s3cr3t-value" in result.stdout
    assert "s3cr3t-value" not in result.stderr
    log_dir = isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel"
    logs = list(log_dir.glob("app.log*"))
    assert logs, "the CLI writes the log file"
    for path in logs:
        assert "s3cr3t-value" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("command", ["chat", "test-agent"])
def test_unknown_agent_lists_available(isolated_env, command: str) -> None:
    args = [command, "no-such-agent"] + (["hej"] if command == "chat" else [])
    result = cli(*args)
    assert result.returncode == 2
    assert "nieznany agent „no-such-agent”" in result.stderr
    assert "Dostępni agenci:" in result.stderr
    assert "fake-echo" in result.stderr and "fake-missing" in result.stderr
    assert result.stdout == ""


def test_unknown_agent_without_config(isolated_env, tmp_path: Path) -> None:
    result = cli("test-agent", "x", env_extra={"AI_PANEL_CONFIG": str(tmp_path / "none.toml")})
    assert result.returncode == 2
    assert "Brak skonfigurowanych agentów." in result.stderr


def test_skipped_agent_is_reported(isolated_env, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[agents.broken]\ntype = "acp"\ncwd = "/tmp"\n', encoding="utf-8")
    config.chmod(0o600)
    result = cli("chat", "broken", "x", env_extra={"AI_PANEL_CONFIG": str(config)})
    assert result.returncode == 2
    assert "ma błędy konfiguracji" in result.stderr and "check-config" in result.stderr


def test_api_agent_is_not_supported_yet(isolated_env, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[agents.api]\ntype = "api"\nendpoint = "https://example.invalid/v1"\nmodel = "m"\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    for args in (("chat", "api", "x"), ("test-agent", "api")):
        result = cli(*args, env_extra={"AI_PANEL_CONFIG": str(config)})
        assert result.returncode == 2
        assert "typu „api”" in result.stderr
        assert_no_traceback(result)


def test_test_agent_ok(isolated_env) -> None:
    result = cli("test-agent", "fake-echo")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Fake ACP Agent (fake-acp-agent) 1.0.0" in result.stdout
    assert "protokół: 1" in result.stdout
    assert "OK:" in result.stdout
    assert_no_traceback(result)


def test_test_agent_failures_have_distinct_messages(isolated_env) -> None:
    expected = {
        "fake-missing": "Nie znaleziono polecenia",
        "fake-badver": "Nieobsługiwana wersja protokołu",
        "fake-auth": "Agent wymaga zalogowania. Dostępne metody: Fake login",
        "fake-crash": None,  # crash happens only after session/prompt: the test passes
    }
    messages = set()
    for agent_id, needle in expected.items():
        result = cli("test-agent", agent_id)
        assert_no_traceback(result)
        if needle is None:
            assert result.returncode == 0
            continue
        assert result.returncode == 2, result.stdout
        assert needle in result.stdout
        failure = next(
            line for line in result.stdout.splitlines() if line.startswith("Test połączenia")
        )
        messages.add(failure)
    assert len(messages) == 3


def test_test_agent_auth_lists_methods(isolated_env) -> None:
    result = cli("test-agent", "fake-auth")
    assert result.returncode == 2
    assert "protokół: 1" in result.stdout
    assert "metody logowania: Fake login" in result.stdout


def test_test_agent_leaves_no_process(isolated_env) -> None:
    result = cli("test-agent", "fake-echo")
    assert result.returncode == 0
    # The CLI exited, so its agent must be gone too: no process runs in the agent's cwd.
    cwd = isolated_env["HOME"] / ".cache" / "gnome-ai-panel-fake" / "echo"
    assert cwd.is_dir()
    left = []
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            try:
                if Path(os.readlink(proc / "cwd")) == cwd:
                    left.append(proc.name)
            except OSError:
                continue
    assert left == []
