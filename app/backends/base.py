"""Events produced by backends and the ``Backend`` interface (FR-18, PLAN §11.2).

Backends (ACP agent, Anthropic API) turn their protocol into these events; the controller and
the CLI consume them without knowing which backend produced them. ``event_to_dict`` gives the
JSON form used by the JS bridge (PLAN §12.2) and by ``cli chat --json``.

This module must not import GTK.
"""

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

# {"type": "text", "text": ...} or {"type": "image", "mimeType": ..., "data": <base64>}
type ContentPart = dict[str, Any]

type ErrorKind = Literal["spawn", "timeout", "protocol", "auth", "http", "crashed", "other"]
ERROR_KINDS: tuple[str, ...] = ("spawn", "timeout", "protocol", "auth", "http", "crashed", "other")


@dataclass(frozen=True, slots=True)
class TextDelta:
    TYPE: ClassVar[str] = "text_delta"
    text: str


@dataclass(frozen=True, slots=True)
class ThinkingDelta:
    TYPE: ClassVar[str] = "thinking_delta"
    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    TYPE: ClassVar[str] = "tool_call"
    id: str
    title: str = ""
    kind: str | None = None
    status: str | None = None
    raw_input: Any = None
    content: Any = None


@dataclass(frozen=True, slots=True)
class ToolUpdate:
    """Only the fields the agent sent are set; ``None`` means "unchanged"."""

    TYPE: ClassVar[str] = "tool_update"
    id: str
    status: str | None = None
    title: str | None = None
    raw_input: Any = None
    content: Any = None


@dataclass(frozen=True, slots=True)
class PermissionOption:
    id: str
    name: str
    kind: str | None = None  # ACP: allow_once, allow_always, reject_once, reject_always


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    """Answer with ``Backend.respond_permission(request_id, option_id | None)``."""

    TYPE: ClassVar[str] = "permission_request"
    request_id: str
    tool_call_id: str | None = None
    title: str = ""
    kind: str | None = None
    raw_input: Any = None
    options: list[PermissionOption] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConfigOptions:
    TYPE: ClassVar[str] = "config_options"
    options: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Usage:
    TYPE: ClassVar[str] = "usage"
    used: int | None = None
    size: int | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None


@dataclass(frozen=True, slots=True)
class Done:
    TYPE: ClassVar[str] = "done"
    stop_reason: str


@dataclass(frozen=True, slots=True)
class Error:
    """``auth_methods``: the agent's ``authMethods`` (kind ``auth``); ``stderr``: the last
    lines the agent wrote to stderr (kind ``crashed``)."""

    TYPE: ClassVar[str] = "error"
    message: str
    kind: ErrorKind = "other"
    auth_methods: list[dict[str, Any]] | None = None
    stderr: str | None = None


class BackendError(Exception):
    """Raised by ``Backend.new_session`` and friends; ``event`` is the ``Error`` to show."""

    def __init__(self, event: Error) -> None:
        super().__init__(event.message)
        self.event = event

    @property
    def kind(self) -> str:
        return self.event.kind


type Event = (
    TextDelta
    | ThinkingDelta
    | ToolCall
    | ToolUpdate
    | PermissionRequest
    | ConfigOptions
    | Usage
    | Done
    | Error
)

EVENT_TYPES: tuple[type, ...] = (
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolUpdate,
    PermissionRequest,
    ConfigOptions,
    Usage,
    Done,
    Error,
)


def event_to_dict(event: Event) -> dict[str, Any]:
    """``{"type": "<snake_case name>", **fields}``, JSON-serialisable when the payload is."""
    result: dict[str, Any] = {"type": event.TYPE}
    for f in fields(event):
        value = getattr(event, f.name)
        if f.name == "options" and isinstance(event, PermissionRequest):
            value = [asdict(option) for option in value]
        result[f.name] = value
    return result


@runtime_checkable
class Backend(Protocol):
    """One agent (ACP process or API endpoint) serving any number of sessions."""

    name: str

    async def new_session(self) -> str:
        """Start a conversation and return its session id."""
        ...

    def send(self, session_id: str, prompt: list[ContentPart]) -> AsyncIterator[Event]:
        """Run one turn. The iterator ends after ``Done`` or ``Error``."""
        ...

    def respond_permission(self, request_id: str, option_id: str | None) -> None:
        """Answer a ``PermissionRequest``; ``None`` rejects (or cancels) it."""
        ...

    async def cancel(self, session_id: str) -> None:
        """Ask the backend to stop the running turn; ``send`` then yields ``Done("cancelled")``."""
        ...

    async def set_option(self, session_id: str, config_id: str, value: str) -> None:
        """Change a session option (e.g. the model)."""
        ...

    async def close(self) -> None:
        """Release the process or connection. Safe to call more than once."""
        ...
