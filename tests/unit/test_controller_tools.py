"""ChatController: thinking and tool events of a turn (S4-T1, FR-9, FR-10)."""

import logging

from app.backends.base import Done, Error, TextDelta, ThinkingDelta, ToolCall, ToolUpdate
from tests.unit.test_controller import make, settle

OUTPUT = [{"type": "content", "content": {"type": "text", "text": "zawartość"}}]


async def test_thinking_and_tool_events_keep_their_order() -> None:
    controller, sink, _, _ = make(
        [
            ThinkingDelta("Sprawdzę plik."),
            ToolCall(
                "call_1",
                title="Odczyt pliku notes.txt",
                kind="read",
                status="pending",
                raw_input={"path": "notes.txt"},
            ),
            ToolUpdate("call_1", status="in_progress"),
            ToolUpdate("call_1", status="completed", content=OUTPUT),
            TextDelta("Plik zawiera: zawartość."),
            Done("end_turn"),
        ]
    )
    controller.send("x")
    await settle(controller)
    assert sink.events == [
        {"type": "turn_start"},
        {"type": "thinking_delta", "text": "Sprawdzę plik."},
        {
            "type": "tool_call",
            "id": "call_1",
            "title": "Odczyt pliku notes.txt",
            "kind": "read",
            "status": "pending",
            "raw_input": {"path": "notes.txt"},
            "content": None,
        },
        {"type": "tool_update", "id": "call_1", "status": "in_progress"},
        {"type": "tool_update", "id": "call_1", "status": "completed", "content": OUTPUT},
        {"type": "text_delta", "text": "Plik zawiera: zawartość."},
        {"type": "done", "stop_reason": "end_turn"},
    ]
    assert controller.messages[-1] == {
        "role": "assistant",
        "parts": [{"type": "text", "text": "Plik zawiera: zawartość."}],
        "thinking": "Sprawdzę plik.",
        "tools": [
            {
                "id": "call_1",
                "title": "Odczyt pliku notes.txt",
                "status": "completed",
                "input": {"path": "notes.txt"},
                "output": OUTPUT,
            }
        ],
        "stop_reason": "end_turn",
    }


async def test_update_of_unknown_tool_is_dropped(caplog) -> None:
    controller, sink, _, _ = make(
        [
            ToolCall("a", title="A"),
            ToolUpdate("b", status="failed"),
            ToolUpdate("a", title="A2", raw_input="ls"),
            Done("end_turn"),
        ]
    )
    with caplog.at_level(logging.DEBUG, logger="app.controller"):
        controller.send("x")
        await settle(controller)
    assert [e for e in sink.events if e["type"] == "tool_update"] == [
        {"type": "tool_update", "id": "a", "title": "A2", "raw_input": "ls"}
    ]
    assert "update of unknown tool call dropped" in caplog.text
    (tool,) = controller.messages[-1]["tools"]
    # A tool call without a status is stored as pending.
    assert tool == {"id": "a", "title": "A2", "status": "pending", "input": "ls", "output": None}


async def test_repeated_tool_call_replaces_the_stored_call() -> None:
    controller, sink, _, _ = make(
        [
            ToolCall("a", title="A", status="pending"),
            ToolCall("b", title="B", status="pending"),
            ToolCall("a", title="A again", status="in_progress"),
            Done("end_turn"),
        ]
    )
    controller.send("x")
    await settle(controller)
    assert [e["type"] for e in sink.events].count("tool_call") == 3
    tools = controller.messages[-1]["tools"]
    assert [(t["id"], t["title"], t["status"]) for t in tools] == [
        ("a", "A again", "in_progress"),
        ("b", "B", "pending"),
    ]


async def test_empty_thinking_is_not_dispatched_and_not_stored() -> None:
    controller, sink, _, _ = make([ThinkingDelta(""), TextDelta("ok"), Done("end_turn")])
    controller.send("x")
    await settle(controller)
    assert "thinking_delta" not in [e["type"] for e in sink.events]
    assert "thinking" not in controller.messages[-1]
    assert "tools" not in controller.messages[-1]


async def test_tools_are_kept_when_the_turn_ends_with_error() -> None:
    controller, sink, _, _ = make(
        [
            ThinkingDelta("a"),
            ThinkingDelta("b"),
            ToolCall("a", title="A", status="in_progress"),
            Error("boom", kind="crashed"),
        ]
    )
    controller.send("x")
    await settle(controller)
    assert sink.events[-1]["type"] == "error"
    message = controller.messages[-1]
    assert message["thinking"] == "ab"
    assert message["tools"][0]["status"] == "in_progress"


async def test_tool_events_of_the_next_turn_start_fresh() -> None:
    controller, sink, backend, _ = make([ToolCall("a", title="A"), Done("end_turn")])
    controller.send("1")
    await settle(controller)
    backend.script = [ToolUpdate("a", status="completed"), Done("end_turn")]
    controller.send("2")
    await settle(controller)
    # The second turn did not announce "a": its update is dropped.
    assert [e["type"] for e in sink.events].count("tool_update") == 0
    assert "tools" not in controller.messages[-1]


# --- tester (S4-T1) ---------------------------------------------------------------------


async def test_interleaved_thinking_and_tools_keep_order_and_join_thinking() -> None:
    controller, sink, _, _ = make(
        [
            ThinkingDelta("a"),
            ToolCall("t1", title="T1", status="in_progress"),
            ThinkingDelta("b"),
            ToolUpdate("t1", status="failed"),
            ToolCall("t2", title="T2"),
            TextDelta("ok"),
            Done("end_turn"),
        ]
    )
    controller.send("x")
    await settle(controller)
    assert [(e["type"], e.get("id") or e.get("text")) for e in sink.events[1:-1]] == [
        ("thinking_delta", "a"),
        ("tool_call", "t1"),
        ("thinking_delta", "b"),
        ("tool_update", "t1"),
        ("tool_call", "t2"),
        ("text_delta", "ok"),
    ]
    message = controller.messages[-1]
    assert message["thinking"] == "ab"
    assert [(t["id"], t["status"]) for t in message["tools"]] == [
        ("t1", "failed"),
        ("t2", "pending"),
    ]


async def test_update_without_fields_changes_nothing() -> None:
    controller, sink, _, _ = make(
        [
            ToolCall("a", title="A", status="in_progress", raw_input={"k": 1}),
            ToolUpdate("a"),
            Done("end_turn"),
        ]
    )
    controller.send("x")
    await settle(controller)
    assert {"type": "tool_update", "id": "a"} in sink.events
    (tool,) = controller.messages[-1]["tools"]
    assert tool == {
        "id": "a",
        "title": "A",
        "status": "in_progress",
        "input": {"k": 1},
        "output": None,
    }
