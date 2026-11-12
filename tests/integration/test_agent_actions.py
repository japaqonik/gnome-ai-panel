"""D-Bus actions ``agent`` and ``agents`` of the running app and the header state in the
debug dump (S4-T4, PLAN §12.1)."""

import json
import time

import pytest

from tests.integration.test_debug_actions import (
    APP_ID,
    FAKE_CONFIG,
    action,
    dump,
    turn_over,
    wait_dump,
)

pytestmark = pytest.mark.gui


def describe(app, name: str) -> str:
    result = app.run(
        "gdbus", "call", "--session", "-d", APP_ID, "-o", "/pl/local/AiPanel",
        "-m", "org.gtk.Actions.Describe", name,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    return result.stdout


def wait_describe(app, name: str, text: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    out = ""
    while time.monotonic() < deadline:
        out = describe(app, name)
        if text in out:
            return out
        time.sleep(0.1)
    pytest.fail(f"{name}: {text!r} not in {out!r}")


def test_agents_state_lists_configured_agents(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    agents = describe(app, "agents")
    assert "('fake-echo', 'fake-echo')" in agents
    assert "('fake-models', 'fake-models')" in agents
    assert "'fake-missing'" in agents
    assert "'fake-echo'" in describe(app, "agent")


def test_agent_action_switches_agent_and_badge(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    action(app, "debug-send", "a")
    wait_dump(app, lambda s: turn_over(s, 1))

    action(app, "agent", "fake-models")
    wait_describe(app, "agent", "'fake-models'")
    state = wait_dump(app, lambda s: s["agent"] == "fake-models")
    assert state["badge"] == "tools"
    assert state["messages"] == []  # agent change → new conversation

    action(app, "debug-send", "b")
    state = wait_dump(app, lambda s: turn_over(s, 1))
    assert state["messages"][-1]["text"].strip() == "[fake-small] Echo: b"


def test_unknown_agent_is_ignored(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    action(app, "agent", "no-such-agent")
    # SetState goes the same way as activation.
    result = app.run(
        "gdbus", "call", "--session", "-d", APP_ID, "-o", "/pl/local/AiPanel",
        "-m", "org.gtk.Actions.SetState", "agent", "<'also-missing'>", "{}",
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    time.sleep(0.3)
    assert "'fake-echo'" in describe(app, "agent")
    assert dump(app)["agent"] == "fake-echo"


def test_set_state_selects_agent(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    result = app.run(
        "gdbus", "call", "--session", "-d", APP_ID, "-o", "/pl/local/AiPanel",
        "-m", "org.gtk.Actions.SetState", "agent", "<'fake-tool'>", "{}",
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    wait_describe(app, "agent", "'fake-tool'")
    assert wait_dump(app, lambda s: s["agent"] == "fake-tool")["badge"] == "tools"


def test_api_agent_shows_chat_badge_and_unsupported_error(app_process, app_env, tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        FAKE_CONFIG.read_text(encoding="utf-8")
        .replace("../../.venv", str(FAKE_CONFIG.parents[2] / ".venv"))
        .replace("../fakes", str(FAKE_CONFIG.parents[1] / "fakes"))
        + '\n[agents.czat]\ntype = "api"\nname = "Czat"\n'
        'endpoint = "https://127.0.0.1:9/v1/messages"\nmodel = "m"\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    app_env["AI_PANEL_CONFIG"] = str(config)
    app = app_process("--background")
    assert "('czat', 'Czat')" in describe(app, "agents")
    action(app, "agent", "czat")
    state = wait_dump(app, lambda s: s["agent"] == "czat")
    assert state["badge"] == "chat"
    action(app, "debug-send", "x")
    state = wait_dump(app, lambda s: turn_over(s, 1))
    assert state["messages"][-1]["role"] == "error"
    assert "nie jest jeszcze obsługiwany" in json.dumps(state, ensure_ascii=False)
