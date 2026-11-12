"""Backend events and the Backend protocol (S2-T3)."""

import json

from app.backends.base import (
    EVENT_TYPES,
    Backend,
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
    event_to_dict,
)


def test_event_type_names_match_bridge_protocol() -> None:
    assert [t.TYPE for t in EVENT_TYPES] == [
        "text_delta",
        "thinking_delta",
        "tool_call",
        "tool_update",
        "permission_request",
        "config_options",
        "usage",
        "done",
        "error",
    ]


def test_event_to_dict_is_json_serialisable() -> None:
    events = [
        TextDelta("a"),
        ThinkingDelta("b"),
        ToolCall("t1", "Read", "read", "pending", {"path": "x"}, None),
        ToolUpdate("t1", status="completed"),
        PermissionRequest(
            "r1",
            "t1",
            "Write",
            "edit",
            {"p": 1},
            [PermissionOption("allow", "Zezwól", "allow_once")],
        ),
        ConfigOptions([{"id": "model"}]),
        Usage(10, 100, 0.5, "USD"),
        Done("end_turn"),
        Error("Nie znaleziono polecenia: x", "spawn"),
    ]
    for event in events:
        json.dumps(event_to_dict(event))
    assert event_to_dict(Done("end_turn")) == {"type": "done", "stop_reason": "end_turn"}
    assert event_to_dict(ToolUpdate("t1", status="failed")) == {
        "type": "tool_update",
        "id": "t1",
        "status": "failed",
        "title": None,
        "raw_input": None,
        "content": None,
    }
    perm = event_to_dict(events[4])
    assert perm["options"] == [{"id": "allow", "name": "Zezwól", "kind": "allow_once"}]


def test_error_kind_defaults_to_other() -> None:
    assert Error("x").kind == "other"


def test_backend_protocol_is_structural() -> None:
    class Dummy:
        name = "d"

        async def new_session(self) -> str:
            return "s"

        async def send(self, session_id, prompt):
            yield Done("end_turn")

        def respond_permission(self, request_id, option_id) -> None:
            pass

        async def cancel(self, session_id) -> None:
            pass

        def config_options(self, session_id) -> list:
            return []

        async def set_option(self, session_id, config_id, value) -> None:
            return None

        async def close(self) -> None:
            pass

    assert isinstance(Dummy(), Backend)
