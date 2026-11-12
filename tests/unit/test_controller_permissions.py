"""ChatController: permission requests and answers (S4-T2, FR-11)."""

import asyncio
import logging

from app.backends.base import Done, PermissionOption, PermissionRequest, TextDelta
from tests.unit.test_controller import FakeBackend, make, settle

OPTIONS = [
    PermissionOption("allow", "Zezwól", "allow_once"),
    PermissionOption("reject", "Odrzuć", "reject_once"),
]


def request(request_id: str = "perm-1", **extra) -> PermissionRequest:
    return PermissionRequest(
        request_id,
        tool_call_id=extra.pop("tool_call_id", "call_perm"),
        title=extra.pop("title", "Zapis pliku out.txt"),
        kind=extra.pop("kind", "edit"),
        raw_input=extra.pop("raw_input", {"path": "out.txt", "content": "x"}),
        options=extra.pop("options", OPTIONS),
    )


class AskingBackend(FakeBackend):
    """Yields the permission requests of ``requests``, then waits until each one is answered
    (or the turn is cancelled) and replies with the chosen option ids."""

    def __init__(self, requests: list[PermissionRequest]) -> None:
        super().__init__()
        self.requests = requests
        self._answered = asyncio.Event()

    async def send(self, session_id, prompt):
        self.prompts.append((session_id, prompt))
        self._cancelled.clear()
        try:
            for item in self.requests:
                yield item
            while len(self.permissions) < len(self.requests):
                self._answered.clear()
                waiter = asyncio.ensure_future(self._answered.wait())
                cancelled = asyncio.ensure_future(self._cancelled.wait())
                done, pending = await asyncio.wait(
                    {waiter, cancelled}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if cancelled in done:
                    yield Done("cancelled")
                    return
            yield TextDelta(",".join(str(option) for _, option in self.permissions))
            yield Done("end_turn")
        finally:
            self.closed_iterators += 1

    def respond_permission(self, request_id, option_id) -> None:
        super().respond_permission(request_id, option_id)
        self._answered.set()


async def wait_for(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def started(backend: AskingBackend):
    controller, sink, _, _ = make(backend=backend)
    controller.send("zrób")
    return controller, sink


async def test_request_is_dispatched_with_all_fields() -> None:
    backend = AskingBackend([request()])
    controller, sink = started(backend)
    await wait_for(lambda: "permission_request" in sink.types())
    assert sink.events[1] == {
        "type": "permission_request",
        "request_id": "perm-1",
        "tool_call_id": "call_perm",
        "title": "Zapis pliku out.txt",
        "kind": "edit",
        "raw_input": {"path": "out.txt", "content": "x"},
        "options": [
            {"id": "allow", "name": "Zezwól", "kind": "allow_once"},
            {"id": "reject", "name": "Odrzuć", "kind": "reject_once"},
        ],
    }
    await asyncio.sleep(0.05)
    assert controller.busy  # no automatic answer: the turn waits for the user
    assert backend.permissions == []
    controller.cancel()
    await settle(controller)


async def test_answer_goes_to_the_backend() -> None:
    backend = AskingBackend([request()])
    controller, sink = started(backend)
    await wait_for(lambda: "permission_request" in sink.types())
    controller.permission("perm-1", "allow")
    await settle(controller)
    assert backend.permissions == [("perm-1", "allow")]
    assert sink.events[-2:] == [
        {"type": "text_delta", "text": "allow"},
        {"type": "done", "stop_reason": "end_turn"},
    ]


async def test_null_answer_rejects() -> None:
    backend = AskingBackend([request()])
    controller, sink = started(backend)
    await wait_for(lambda: "permission_request" in sink.types())
    controller.permission("perm-1", None)
    await settle(controller)
    assert backend.permissions == [("perm-1", None)]


async def test_unknown_option_is_answered_as_reject(caplog) -> None:
    backend = AskingBackend([request()])
    controller, sink = started(backend)
    await wait_for(lambda: "permission_request" in sink.types())
    with caplog.at_level(logging.WARNING, logger="app.controller"):
        controller.permission("perm-1", "allow_everything")
    await settle(controller)
    assert backend.permissions == [("perm-1", None)]
    assert any("unknown option" in m for m in caplog.messages)
    assert "allow_everything" not in caplog.text


async def test_answer_counts_once_and_unknown_requests_are_dropped(caplog) -> None:
    backend = AskingBackend([request("perm-1"), request("perm-2")])
    controller, sink = started(backend)
    await wait_for(lambda: sink.types().count("permission_request") == 2)
    with caplog.at_level(logging.WARNING, logger="app.controller"):
        controller.permission("perm-404", "allow")
        controller.permission("perm-1", "allow")
        controller.permission("perm-1", "reject")  # second answer: dropped
    assert backend.permissions == [("perm-1", "allow")]
    assert controller.busy
    controller.permission("perm-2", "reject")
    await settle(controller)
    assert backend.permissions == [("perm-1", "allow"), ("perm-2", "reject")]
    assert sink.events[-1] == {"type": "done", "stop_reason": "end_turn"}
    assert sum("unknown request" in m for m in caplog.messages) == 2


async def test_answer_without_turn_is_dropped() -> None:
    controller, sink, backend, _ = make()
    controller.permission("perm-1", "allow")
    assert backend.permissions == []
    assert sink.events == []


async def test_answer_after_the_turn_ended_is_dropped() -> None:
    backend = AskingBackend([request()])
    controller, sink = started(backend)
    await wait_for(lambda: "permission_request" in sink.types())
    controller.cancel()
    await settle(controller)
    assert sink.events[-1] == {"type": "done", "stop_reason": "cancelled"}
    controller.permission("perm-1", "allow")
    assert backend.permissions == []


async def test_new_chat_with_open_request_ends_the_turn() -> None:
    backend = AskingBackend([request()])
    controller, sink = started(backend)
    await wait_for(lambda: "permission_request" in sink.types())
    controller.new_chat()
    await settle(controller)
    assert sink.types()[-2:] == ["done", "conversation"]
    controller.permission("perm-1", "allow")
    assert backend.permissions == []
    assert backend.closed_iterators == 1
