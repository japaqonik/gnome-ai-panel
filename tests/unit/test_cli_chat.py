"""Unit tests of the chat/test-agent helpers in app/cli.py and of app/diagnostics.py (S2-T5)."""

import argparse
import asyncio
import io
import json
import sys
from pathlib import Path

import pytest

from app import cli, diagnostics
from app.backends.base import (
    BackendError,
    ConfigOptions,
    Done,
    Error,
    PermissionOption,
    PermissionRequest,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolUpdate,
    Usage,
)
from app.config import AcpAgent, ApiAgent

FAKE = Path(__file__).resolve().parent.parent / "fakes" / "fake_acp_agent.py"

ALLOW = PermissionOption("a1", "Zezwól", "allow_once")
ALWAYS = PermissionOption("a2", "Zawsze", "allow_always")
REJECT = PermissionOption("r1", "Odrzuć", "reject_once")


def printer() -> tuple[cli.TextPrinter, io.StringIO, io.StringIO]:
    out, err = io.StringIO(), io.StringIO()
    return cli.TextPrinter(out, err), out, err


# -- choose_permission -------------------------------------------------------------------------


def test_choose_permission_deny_always_rejects() -> None:
    assert cli.choose_permission([ALLOW, REJECT], "deny") is None


def test_choose_permission_allow_prefers_allow_once() -> None:
    assert cli.choose_permission([ALWAYS, REJECT, ALLOW], "allow") == "a1"
    assert cli.choose_permission([REJECT, ALWAYS], "allow") == "a2"


def test_choose_permission_allow_without_allow_option_rejects() -> None:
    assert cli.choose_permission([REJECT, PermissionOption("x", "?", None)], "allow") is None
    assert cli.choose_permission([], "allow") is None


# -- seconds -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "expected"), [("0", 0.0), ("0.5", 0.5), ("3", 3.0)])
def test_seconds_accepts_non_negative(value: str, expected: float) -> None:
    assert cli.seconds(value) == expected


@pytest.mark.parametrize("value", ["-0.1", "x", "", "nan", "inf", "-inf"])
def test_seconds_rejects(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        cli.seconds(value)


def test_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["chat", "a", "b"])
    assert (args.agent_id, args.prompt, args.json) == ("a", "b", False)
    assert args.permission == "deny" and args.cancel_after is None
    args = cli.build_parser().parse_args(["test-agent", "a"])
    assert args.func is cli.cmd_test_agent


def test_parser_rejects_unknown_permission(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["chat", "a", "b", "--permission", "always"])
    assert exc.value.code == 2


# -- TextPrinter -------------------------------------------------------------------------------


def test_text_printer_streams_text_and_prefixes_thinking() -> None:
    p, out, _ = printer()
    p.event(ThinkingDelta("Myślę"))
    p.event(ThinkingDelta(" dalej\ni jeszcze"))
    p.event(TextDelta("Echo: "))
    p.event(TextDelta("Cześć"))
    p.event(Done("end_turn"))
    assert out.getvalue() == ("[thinking] Myślę dalej\n[thinking] i jeszcze\nEcho: Cześć\n")


def test_text_printer_tool_lines_break_the_text() -> None:
    p, out, _ = printer()
    p.event(TextDelta("Zaczynam"))
    p.event(ToolCall("t1", "Odczyt", "read", "pending"))
    p.event(ToolUpdate("t1", status="in_progress"))
    p.event(ToolUpdate("t1"))  # nothing new: no line
    content = [{"type": "content", "content": {"type": "text", "text": "a\n  b"}}]
    p.event(ToolUpdate("t1", status="completed", content=content))
    p.event(ToolUpdate("t2", status="failed"))
    p.event(TextDelta("Koniec"))
    p.event(Done("end_turn"))
    assert out.getvalue().splitlines() == [
        "Zaczynam",
        "[tool] Odczyt (read, pending)",
        "[tool] Odczyt: in_progress",
        "[tool] Odczyt: completed – a b",
        "[tool] narzędzie t2: failed",
        "Koniec",
    ]


def test_text_printer_tool_snippet_is_shortened() -> None:
    p, out, _ = printer()
    content = [{"type": "content", "content": {"type": "text", "text": "x" * 500}}]
    p.event(ToolUpdate("t", status="completed", content=content))
    line = out.getvalue().rstrip("\n")
    assert line.endswith("…")
    assert len(line) < 300


def test_text_printer_permission_lines() -> None:
    p, out, _ = printer()
    request = PermissionRequest("perm-1", "t1", "Zapis", "edit", None, [ALLOW, REJECT])
    p.event(request)
    p.permission_answer(request, None)
    p.permission_answer(request, "a1")
    no_allow = PermissionRequest("perm-2", "t2", "", None, None, [REJECT])
    p.permission_answer(no_allow, None)
    assert out.getvalue().splitlines() == [
        "[permission] Zapis: prośba o zgodę, opcje: Zezwól [allow_once], Odrzuć [reject_once]",
        "[permission] Zapis → odrzucono (domyślnie; --permission allow zezwala)",
        "[permission] Zapis → zezwolono (Zezwól)",
        "[permission] narzędzie t2 → odrzucono (agent nie podał opcji zezwolenia)",
    ]


def test_text_printer_usage_options_done_reason() -> None:
    p, out, _ = printer()
    p.event(Usage(used=10, size=100, cost_amount=0.5, cost_currency="USD"))
    p.event(Usage())
    p.event(ConfigOptions([{"id": "model", "name": "Model", "currentValue": "m1"}, {"id": "x"}]))
    p.event(TextDelta("abc"))
    p.event(Done("cancelled"))
    assert out.getvalue().splitlines() == [
        "[usage] użyto 10 z 100 tokenów, koszt 0.5 USD",
        "[usage] użyto ? z ? tokenów",
        "[options] Model=m1, x",
        "abc",
        "[done] cancelled",
    ]


def test_text_printer_error_goes_to_stderr() -> None:
    p, out, err = printer()
    p.event(TextDelta("częściowo"))
    p.event(Error("Proces agenta zakończył działanie (kod 3).", "crashed"))
    assert out.getvalue() == "częściowo\n"
    assert err.getvalue() == "błąd: Proces agenta zakończył działanie (kod 3).\n"


# -- JsonPrinter -------------------------------------------------------------------------------


def test_json_printer_one_object_per_line() -> None:
    out = io.StringIO()
    p = cli.JsonPrinter(out)
    request = PermissionRequest("perm-1", "t1", "Zapis", "edit", {"path": "ą"}, [ALLOW])
    p.event(TextDelta("Cześć"))
    p.event(request)
    p.permission_answer(request, "a1")
    p.event(Done("end_turn"))
    lines = out.getvalue().splitlines()
    objects = [json.loads(line) for line in lines]
    assert [o["type"] for o in objects] == [
        "text_delta",
        "permission_request",
        "permission_response",
        "done",
    ]
    assert "Cześć" in lines[0]  # not \u-escaped
    assert objects[1]["options"] == [{"id": "a1", "name": "Zezwól", "kind": "allow_once"}]
    assert objects[2] == {
        "type": "permission_response",
        "request_id": "perm-1",
        "option_id": "a1",
        "allowed": True,
    }
    assert objects[3] == {"type": "done", "stop_reason": "end_turn"}


# -- run_chat with a scripted backend ----------------------------------------------------------


class ScriptedBackend:
    name = "scripted"

    def __init__(self, events, *, fail: Error | None = None) -> None:
        self.events = events
        self.fail = fail
        self.answers: list[tuple[str, str | None]] = []
        self.cancelled: list[str] = []

    async def new_session(self) -> str:
        if self.fail is not None:
            raise BackendError(self.fail)
        return "s1"

    async def send(self, session_id, prompt):
        assert prompt == [{"type": "text", "text": "hej"}]
        for event in self.events:
            yield event

    def respond_permission(self, request_id, option_id) -> None:
        self.answers.append((request_id, option_id))

    async def cancel(self, session_id) -> None:
        self.cancelled.append(session_id)

    async def set_option(self, session_id, config_id, value) -> None:
        pass

    async def close(self) -> None:
        pass


async def test_run_chat_done_is_exit_0_and_permissions_answered() -> None:
    request = PermissionRequest("perm-1", None, "Zapis", None, None, [ALLOW, REJECT])
    backend = ScriptedBackend([request, TextDelta("ok"), Done("end_turn")])
    out = io.StringIO()
    code = await cli.run_chat(backend, "hej", cli.JsonPrinter(out), permission="allow")
    assert code == 0
    assert backend.answers == [("perm-1", "a1")]
    assert json.loads(out.getvalue().splitlines()[-1])["type"] == "done"


async def test_run_chat_default_denies() -> None:
    request = PermissionRequest("perm-1", None, "Zapis", None, None, [ALLOW, REJECT])
    backend = ScriptedBackend([request, Done("end_turn")])
    p, _, _ = printer()
    assert await cli.run_chat(backend, "hej", p) == 0
    assert backend.answers == [("perm-1", None)]


async def test_run_chat_error_is_exit_2() -> None:
    backend = ScriptedBackend([TextDelta("x"), Error("boom", "crashed")])
    p, _, err = printer()
    assert await cli.run_chat(backend, "hej", p) == 2
    assert "błąd: boom" in err.getvalue()


async def test_run_chat_new_session_failure_is_exit_2() -> None:
    backend = ScriptedBackend([], fail=Error("Agent wymaga zalogowania.", "auth"))
    out = io.StringIO()
    assert await cli.run_chat(backend, "hej", cli.JsonPrinter(out)) == 2
    assert json.loads(out.getvalue()) == {
        "type": "error",
        "message": "Agent wymaga zalogowania.",
        "kind": "auth",
        "auth_methods": None,
        "stderr": None,
    }


async def test_run_chat_stream_without_done_is_exit_2() -> None:
    p, _, _ = printer()
    assert await cli.run_chat(ScriptedBackend([TextDelta("x")]), "hej", p) == 2


# -- diagnostics -------------------------------------------------------------------------------


def fake_agent(tmp_path: Path, scenario: str, **kwargs) -> AcpAgent:
    return AcpAgent(
        id=f"fake-{scenario}",
        name=f"Fake {scenario}",
        command=kwargs.pop("command", sys.executable),
        args=[str(FAKE), "--scenario", scenario],
        cwd=tmp_path / "cwd",
        **kwargs,
    )


def test_describe_agent() -> None:
    d = diagnostics.describe_agent
    assert d({"name": "n", "title": "T", "version": "1.0"}) == "T (n) 1.0"
    assert d({"name": "n", "title": "n"}) == "n"
    assert d({"version": "2"}) == "2"
    assert d({"name": 5}) == strings_unknown()
    assert d(None) == strings_unknown()


def strings_unknown() -> str:
    return diagnostics.strings.DIAG_UNKNOWN_AGENT_INFO


def test_describe_error_adds_hint_per_kind() -> None:
    messages = {
        kind: diagnostics.describe_error(Error("x", kind))
        for kind in ("spawn", "timeout", "protocol", "crashed")
    }
    assert len(set(messages.values())) == 4
    assert all(m.startswith("x\n") for m in messages.values())
    assert diagnostics.describe_error(Error("y", "auth")) == "y"
    assert diagnostics.describe_error(Error("z", "other")) == "z"


def test_test_result_is_not_collected_by_pytest() -> None:
    assert diagnostics.TestResult.__test__ is False
    assert diagnostics.test_agent.__test__ is False


async def test_test_agent_ok(isolated_env, tmp_path) -> None:
    result = await diagnostics.test_agent(fake_agent(tmp_path, "echo"))
    assert result.ok and result.error is None
    assert result.protocol_version == 1
    assert result.agent_info == {
        "name": "fake-acp-agent",
        "title": "Fake ACP Agent",
        "version": "1.0.0",
    }
    assert result.auth_methods == []


async def test_test_agent_missing_command(isolated_env, tmp_path) -> None:
    agent = fake_agent(tmp_path, "echo", command="/nonexistent/agent")
    result = await diagnostics.test_agent(agent)
    assert not result.ok
    assert result.error is not None and result.error.kind == "spawn"
    assert "Nie znaleziono polecenia" in result.error.message
    assert result.protocol_version is None and result.agent_info is None


async def test_test_agent_bad_version(isolated_env, tmp_path) -> None:
    result = await diagnostics.test_agent(fake_agent(tmp_path, "bad-version"))
    assert result.error is not None and result.error.kind == "protocol"
    assert "99" in result.error.message


async def test_test_agent_auth_keeps_initialize_info(isolated_env, tmp_path) -> None:
    result = await diagnostics.test_agent(fake_agent(tmp_path, "auth"))
    assert not result.ok
    assert result.error is not None and result.error.kind == "auth"
    assert result.protocol_version == 1
    assert [m["id"] for m in result.auth_methods] == ["fake-login"]


async def test_test_agent_timeout(isolated_env, tmp_path) -> None:
    agent = AcpAgent(
        id="sleepy",
        name="sleepy",
        command=sys.executable,
        args=["-c", "import time; time.sleep(30)"],
        cwd=tmp_path / "cwd",
        startup_timeout_s=0.5,
    )
    result = await diagnostics.test_agent(agent)
    assert result.error is not None and result.error.kind == "timeout"


async def test_test_agent_api_type_not_supported(isolated_env) -> None:
    agent = ApiAgent(id="api", name="api", endpoint="https://example.invalid", model="m")
    result = await diagnostics.test_agent(agent)
    assert not result.ok
    assert result.error is not None and "api" in result.error.message


async def test_test_agent_unexpected_exception_is_reported(
    isolated_env, tmp_path, monkeypatch
) -> None:
    async def broken_start(self) -> None:
        raise RuntimeError("nieoczekiwane")

    monkeypatch.setattr(diagnostics.AcpBackend, "start", broken_start)
    result = await diagnostics.test_agent(fake_agent(tmp_path, "echo"))
    assert not result.ok
    assert result.error is not None and "nieoczekiwane" in result.error.message


class LazyTurnBackend(ScriptedBackend):
    """Like AcpBackend: the turn exists only once iteration of ``send()`` has started, and
    ``cancel()`` without a running turn is a no-op."""

    def __init__(self) -> None:
        super().__init__([])
        self.turn: asyncio.Event | None = None

    async def send(self, session_id, prompt):
        self.turn = asyncio.Event()
        try:
            try:
                await asyncio.wait_for(self.turn.wait(), timeout=5)
            except TimeoutError:
                yield Done("end_turn")
                return
            yield Done("cancelled")
        finally:
            self.turn = None

    async def cancel(self, session_id) -> None:
        if self.turn is not None:
            self.cancelled.append(session_id)
            self.turn.set()


async def test_run_chat_cancel_after_zero_cancels_running_turn() -> None:
    backend = LazyTurnBackend()
    out = io.StringIO()
    code = await cli.run_chat(backend, "hej", cli.JsonPrinter(out), cancel_after=0)
    assert code == 0
    assert backend.cancelled == ["s1"]
    assert json.loads(out.getvalue().splitlines()[-1]) == {
        "type": "done",
        "stop_reason": "cancelled",
    }
