"""Debug actions, link policy and theme of the running app (S3-T4), driven over D-Bus.

The app runs as ``python -m app --background`` on a private bus (``app_process``). Prompts go
in through ``debug-send``, links are clicked with ``debug-click`` and the page state is read
with ``python -m app.cli ui-dump`` (``debug-dump``). ``AI_PANEL_URI_LOG`` makes the app write
launched URIs to a file, so no browser is opened.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

APP_ID = "pl.local.AiPanel"
REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_CONFIG = REPO_ROOT / "tests" / "data" / "config_fake.toml"
DEBUG_ACTIONS = {"debug-send", "debug-click", "debug-dump"}
INDEX_URI = (REPO_ROOT / "app" / "ui" / "index.html").as_uri()


def ui_dump(app) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "app.cli", "ui-dump"],
        cwd=REPO_ROOT,
        env=app.env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def dump(app) -> dict:
    result = ui_dump(app)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def wait_dump(app, predicate, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = dump(app)
        if predicate(state):
            return state
        time.sleep(0.2)
    pytest.fail(f"state not reached within {timeout} s: {json.dumps(state, ensure_ascii=False)}")


def turn_over(state: dict, count: int) -> bool:
    """``count`` assistant/error messages are there and no turn is running."""
    replies = [m for m in state["messages"] if m["role"] in ("assistant", "error")]
    return not state["busy"] and len(replies) >= count


def action(app, name: str, value: str | None = None) -> None:
    argv = ["gapplication", "action", APP_ID, name]
    if value is not None:
        argv.append(json.dumps(value))  # a GVariant string literal: "…"
    result = app.run(*argv)
    assert result.returncode == 0, result.stderr


def listed_actions(app) -> set[str]:
    result = app.run(
        "gdbus", "call", "--session", "-d", APP_ID, "-o", "/pl/local/AiPanel",
        "-m", "org.gtk.Actions.List",
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    return set(re.findall(r"'([a-z-]+)'", result.stdout))


def write_agent_config(path: Path, *, theme: str) -> Path:
    python = REPO_ROOT / ".venv" / "bin" / "python"
    fake = REPO_ROOT / "tests" / "fakes" / "fake_acp_agent.py"
    work = path.parent / "work"
    work.mkdir(exist_ok=True)
    path.write_text(
        f"""
default_agent = "echo"

[agents.echo]
type = "acp"
command = {json.dumps(str(python))}
args = [{json.dumps(str(fake))}, "--scenario", "echo"]
cwd = {json.dumps(str(work))}

[chat]
theme = "{theme}"
font_size = 17
""",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


# -- registration ---------------------------------------------------------------------------


def test_debug_actions_exist_with_ai_panel_debug(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    assert listed_actions(app) >= DEBUG_ACTIONS


def test_no_debug_actions_without_ai_panel_debug(app_process, app_env) -> None:
    app_env.pop("AI_PANEL_DEBUG", None)
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    names = listed_actions(app)
    assert "toggle" in names
    assert not names & DEBUG_ACTIONS
    result = ui_dump(app)
    assert result.returncode == 1
    assert "debug-dump" in result.stderr
    assert result.stdout == ""


def test_ui_dump_without_app_fails(private_bus, app_env) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "ui-dump"],
        cwd=REPO_ROOT,
        env=app_env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert result.stderr.startswith("błąd: ")


# -- full turn ------------------------------------------------------------------------------


def test_full_turn_through_debug_send(app_process, app_env, isolated_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    action(app, "debug-send", "md: tabela")
    state = wait_dump(app, lambda s: turn_over(s, 1))

    assert state["screen"] == "chat"
    assert state["agent"] == "fake-echo"
    assert state["badge"] == "tools"
    assert state["visible"] is False
    assert state["pinned"] is False
    assert state["permission_dialog"] == {"open": False, "title": ""}
    assert state["banner"] is None
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    assert state["messages"][0]["text"] == "md: tabela"
    last = state["messages"][-1]
    assert "<table" in last["html"]
    assert 'class="hljs' in last["html"]
    assert "Kopiuj" not in last["text"]  # the copy button is not part of the message text
    assert last["thinking"] == ""
    assert last["tools"] == []

    path = isolated_env["XDG_STATE_HOME"] / "gnome-ai-panel" / "debug-dump.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == state


def test_thinking_and_tool_card_through_debug_send(app_process, app_env) -> None:
    # S4-T1: the fake `tool` scenario sends a thought, a tool call and two updates.
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_DEFAULT_AGENT"] = "fake-tool"
    app = app_process("--background")
    action(app, "debug-send", "x")
    state = wait_dump(app, lambda s: turn_over(s, 1))

    last = state["messages"][-1]
    assert last["role"] == "assistant"
    assert last["thinking"] == "Sprawdzę plik."
    assert last["tools"] == [
        {"id": "call_1", "title": "Odczyt pliku notes.txt", "status": "completed"}
    ]
    assert last["text"].strip() == "Plik zawiera: zawartość."
    assert "Sprawdzę" not in last["html"]


def test_permission_dialog_allow_then_reject(app_process, app_env) -> None:
    # S4-T2 / UAT-S4-1: the fake `permission` scenario asks before "writing" out.txt.
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_DEFAULT_AGENT"] = "fake-perm"
    app = app_process("--background")
    for kind, status, text in (
        ("allow_once", "completed", "Zezwolono"),
        ("reject_once", "failed", "Odmowa"),
    ):
        action(app, "debug-send", "zrób")
        state = wait_dump(app, lambda s: s["permission_dialog"]["open"])
        assert state["permission_dialog"] == {"open": True, "title": "Zapis pliku out.txt"}
        assert state["busy"] is True
        time.sleep(0.3)
        assert dump(app)["permission_dialog"]["open"] is True  # nothing chosen automatically
        action(app, "debug-click", f"[data-option-kind={kind}]")
        state = wait_dump(app, lambda s: turn_over(s, 1))
        assert state["permission_dialog"] == {"open": False, "title": ""}
        last = state["messages"][-1]
        assert last["tools"][0]["status"] == status
        assert last["text"].strip() == text
        action(app, "new-chat")
        wait_dump(app, lambda s: s["messages"] == [])


def test_permission_dialog_closes_on_new_chat(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_DEFAULT_AGENT"] = "fake-perm"
    app = app_process("--background")
    action(app, "debug-send", "zrób")
    wait_dump(app, lambda s: s["permission_dialog"]["open"])
    action(app, "new-chat")
    state = wait_dump(app, lambda s: not s["permission_dialog"]["open"] and not s["busy"])
    assert state["messages"] == []
    # The agent got its answer (cancelled): the next turn asks again.
    action(app, "debug-send", "zrób")
    wait_dump(app, lambda s: s["permission_dialog"]["open"])


def test_debug_send_respects_the_busy_check(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_DEFAULT_AGENT"] = "fake-slow"
    app = app_process("--background")
    action(app, "debug-send", "długo")
    wait_dump(app, lambda s: s["busy"])
    action(app, "debug-send", "drugi")  # a turn is running: the page sends nothing
    time.sleep(0.5)
    state = dump(app)
    assert state["busy"] is True
    assert [m["text"] for m in state["messages"] if m["role"] == "user"] == ["długo"]

    action(app, "debug-click", "#stop")
    state = wait_dump(app, lambda s: not s["busy"])
    assert "Przerwano" in state["messages"][-1]["text"]


def test_crash_then_restart_through_debug_send(app_process, app_env) -> None:
    # S4-T3 / UAT-S4-3: fake-crash-once dies on the first prompt (fresh cwd in the test HOME).
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_DEFAULT_AGENT"] = "fake-crash-once"
    app = app_process("--background")
    action(app, "debug-send", "a")
    state = wait_dump(app, lambda s: turn_over(s, 1))
    assert [m["role"] for m in state["messages"]] == ["user", "error"]
    error = state["messages"][-1]
    assert error["kind"] == "crashed"
    assert "boom" in error["text"]
    assert "kod 3" in error["text"]

    action(app, "debug-send", "b")
    state = wait_dump(app, lambda s: turn_over(s, 2))
    assert [m["role"] for m in state["messages"]] == [
        "user",
        "error",
        "user",
        "notice",
        "assistant",
    ]
    assert state["messages"][3]["text"] == (
        "Agent został uruchomiony ponownie, poprzedni kontekst utracony"
    )
    assert state["messages"][-1]["text"].strip() == "Echo: b"


def test_debug_click_with_bad_selector_is_harmless(app_process, app_env) -> None:
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app = app_process("--background")
    action(app, "debug-click", "#no-such-element")
    action(app, "debug-click", "a[[")
    assert dump(app)["screen"] == "chat"
    assert app.proc.poll() is None


# -- links ----------------------------------------------------------------------------------


def test_external_link_goes_to_the_launcher(app_process, app_env, tmp_path) -> None:
    uri_log = tmp_path / "uri.log"
    app_env["AI_PANEL_CONFIG"] = str(FAKE_CONFIG)
    app_env["AI_PANEL_URI_LOG"] = str(uri_log)
    app = app_process("--background")

    # The echo agent repeats the prompt as markdown: a relative link, rendered with
    # data-external like every link. It must neither navigate nor launch anything.
    action(app, "debug-send", "[względny](other.html)")
    state = wait_dump(app, lambda s: turn_over(s, 1))
    assert 'href="other.html"' in state["messages"][-1]["html"]
    action(app, "debug-click", "a[data-external]")
    time.sleep(0.5)
    assert not uri_log.exists()
    assert dump(app)["uri"] == INDEX_URI

    action(app, "new-chat")
    action(app, "debug-send", "md: link")
    wait_dump(app, lambda s: turn_over(s, 1) and "example.com" in s["messages"][-1]["html"])
    action(app, "debug-click", "a[data-external]")
    deadline = time.monotonic() + 5
    # The app creates the file before writing to it: wait for a complete line.
    while time.monotonic() < deadline:
        if uri_log.exists() and uri_log.read_text(encoding="utf-8").endswith("\n"):
            break
        time.sleep(0.05)
    assert uri_log.read_text(encoding="utf-8") == "https://example.com/\n"
    state = dump(app)
    assert state["uri"] == INDEX_URI
    assert state["messages"][-1]["role"] == "assistant"  # the page was not reloaded


# -- theme ----------------------------------------------------------------------------------


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_chat_theme_reaches_the_page(app_process, app_env, tmp_path, theme) -> None:
    app_env["AI_PANEL_CONFIG"] = str(write_agent_config(tmp_path / "config.toml", theme=theme))
    app = app_process("--background")
    state = dump(app)
    assert state["theme"] == theme
    assert state["agent"] == "echo"
