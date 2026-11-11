"""Pure helpers of app/backends/acp.py: session/update mapping and permission outcomes."""

import pytest

from app.backends.acp import (
    AcpBackend,
    format_auth_methods,
    is_auth_error,
    map_session_update,
    parse_permission_options,
    reject_outcome,
)
from app.backends.base import (
    ConfigOptions,
    PermissionOption,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolUpdate,
    Usage,
)
from app.backends.jsonrpc import METHOD_NOT_FOUND, JsonRpcError
from app.config import AcpAgent


def chunk(kind: str, content) -> dict:
    return {"sessionUpdate": kind, "content": content}


def test_message_and_thought_chunks() -> None:
    text = {"type": "text", "text": "a"}
    assert map_session_update(chunk("agent_message_chunk", text)) == TextDelta("a")
    assert map_session_update(chunk("agent_thought_chunk", text)) == ThinkingDelta("a")


@pytest.mark.parametrize(
    "content",
    [{"type": "image", "data": "x", "mimeType": "image/png"}, {"type": "text"}, "a", None],
)
def test_non_text_chunks_are_ignored(content) -> None:
    assert map_session_update(chunk("agent_message_chunk", content)) is None


def test_tool_call() -> None:
    update = {
        "sessionUpdate": "tool_call",
        "toolCallId": "c1",
        "title": "Odczyt",
        "kind": "read",
        "status": "pending",
        "rawInput": {"path": "a"},
        "content": [{"type": "content"}],
    }
    assert map_session_update(update) == ToolCall(
        "c1", "Odczyt", "read", "pending", {"path": "a"}, [{"type": "content"}]
    )


def test_tool_call_without_optional_fields() -> None:
    assert map_session_update({"sessionUpdate": "tool_call", "toolCallId": "c1"}) == ToolCall("c1")


def test_tool_call_update_sets_only_sent_fields() -> None:
    update = {"sessionUpdate": "tool_call_update", "toolCallId": "c1", "status": "completed"}
    assert map_session_update(update) == ToolUpdate("c1", status="completed")


@pytest.mark.parametrize("kind", ["tool_call", "tool_call_update"])
def test_tool_updates_without_id_are_ignored(kind) -> None:
    assert map_session_update({"sessionUpdate": kind, "toolCallId": 5}) is None


def test_config_option_update() -> None:
    options = [{"id": "model", "currentValue": "a"}, "junk"]
    update = {"sessionUpdate": "config_option_update", "configOptions": options}
    assert map_session_update(update) == ConfigOptions([{"id": "model", "currentValue": "a"}])
    assert map_session_update({"sessionUpdate": "config_option_update"}) is None


def test_usage_update() -> None:
    update = {
        "sessionUpdate": "usage_update",
        "used": 10,
        "size": 100,
        "cost": {"amount": 1, "currency": "USD"},
    }
    assert map_session_update(update) == Usage(10, 100, 1.0, "USD")
    bad = {"sessionUpdate": "usage_update", "used": True, "size": "x", "cost": 3}
    assert map_session_update(bad) == Usage()


@pytest.mark.parametrize(
    "update",
    [
        {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "a"}},
        {"sessionUpdate": "plan", "entries": []},
        {"sessionUpdate": "available_commands_update"},
        {"sessionUpdate": "something_new"},
        {},
        None,
        [],
    ],
)
def test_other_updates_are_ignored(update) -> None:
    assert map_session_update(update) is None


def test_parse_permission_options_skips_bad_entries() -> None:
    options = [
        {"optionId": "a", "name": "Zezwól", "kind": "allow_once"},
        {"optionId": "b"},
        {"name": "no id"},
        "junk",
    ]
    assert parse_permission_options(options) == [
        PermissionOption("a", "Zezwól", "allow_once"),
        PermissionOption("b", "b", None),
    ]
    assert parse_permission_options(None) == []


def test_reject_outcome_prefers_reject_once() -> None:
    options = [
        PermissionOption("always", "x", "reject_always"),
        PermissionOption("once", "x", "reject_once"),
        PermissionOption("ok", "x", "allow_once"),
    ]
    assert reject_outcome(options) == {"outcome": "selected", "optionId": "once"}
    assert reject_outcome(options[:1]) == {"outcome": "selected", "optionId": "always"}
    assert reject_outcome(options[2:]) == {"outcome": "cancelled"}


def test_is_auth_error() -> None:
    assert is_auth_error(JsonRpcError(-32000, "Authentication required"))
    assert is_auth_error(JsonRpcError(-32603, "x", {"reason": "auth_required"}))
    assert not is_auth_error(JsonRpcError(-32603, "Internal error"))


def test_format_auth_methods() -> None:
    methods = [{"id": "a", "name": "Login", "description": "run `x login`"}, {"id": "b"}]
    assert format_auth_methods(methods) == "Login (run `x login`); b"
    assert format_auth_methods([]) == "agent nie podał żadnej"


async def test_fs_and_terminal_requests_are_refused(tmp_path) -> None:
    backend = AcpBackend(AcpAgent(id="a", name="a", command="x", cwd=tmp_path))
    with pytest.raises(JsonRpcError) as info:
        await backend._on_request(None, "fs/read_text_file", {"path": "/etc/passwd"})
    assert info.value.code == METHOD_NOT_FOUND
    with pytest.raises(JsonRpcError):
        await backend._on_request(None, "terminal/create", {"command": "rm"})


async def test_permission_for_unknown_session_is_cancelled(tmp_path) -> None:
    backend = AcpBackend(AcpAgent(id="a", name="a", command="x", cwd=tmp_path))
    result = await backend._on_request(None, "session/request_permission", {"sessionId": "s"})
    assert result == {"outcome": {"outcome": "cancelled"}}
