"""Chat controller: the current conversation, the chosen agent and the running turn.

``ChatController`` sits between the UI (any ``UiSink``, in the app ``bridge.Bridge``) and a
backend (``backends.base.Backend``). It receives the UI messages ``ready``, ``send``,
``cancel`` and ``new_chat`` (PLAN §12.2) as method calls and dispatches the events of
the turn to the UI.

Guarantees the UI relies on (``app/ui/chat.js``):

- every ``send`` is answered with exactly one ``done`` or ``error``, also when it is
  rejected (no agent, a turn already running, empty prompt);
- nothing of a turn is dispatched after its ``done``/``error``;
- repeated ``cancel`` messages count as one.

Turn events (S4-T1): ``thinking_delta {text}``, ``tool_call {id, title, kind, status,
raw_input, content}`` and ``tool_update {id, …}`` with only the fields the agent changed.
An update of a tool call the turn has not announced is dropped.

Permissions (S4-T2): a ``PermissionRequest`` becomes ``permission_request {request_id,
tool_call_id, title, kind, raw_input, options: [{id, name, kind}]}``; nothing is answered
until the UI sends ``permission {request_id, option_id|null}``, which goes to
``backend.respond_permission``. Every request is dispatched as it arrives; the page queues
them and shows one dialog at a time. Requests still open when the turn ends (cancel, new
chat, error) are answered by the backend (ACP: ``outcome: cancelled``).

Cancel, failures and restarts (S4-T3):

- ``cancel`` marks the turn's unfinished tool calls (``pending``/``in_progress``) as
  ``cancelled`` at once (``tool_update``), asks the backend to cancel (ACP:
  ``session/cancel``) and waits for the backend's ``done``. An agent that does not end the
  turn within ``cancel_timeout_s`` is given up on: the turn ends with ``done cancelled`` and
  the next prompt starts a new session (with a ``notice``);
- a backend ``Error`` becomes ``error {kind, title, message, hint, stderr, stderr_label,
  auth_methods, methods_label, blocked}`` with the texts of ``app/strings.py``;
- after ``crashed`` the next prompt creates a new session (the backend restarts the agent)
  and the page gets ``notice {kind: "context_lost", text}`` before the reply;
- when the backend refuses to restart the agent (``RestartLimitError``) the conversation is
  blocked: every ``send`` is answered with an ``error`` with ``blocked: true`` until
  ``new_chat``.

Agent and model (S4-T4):

- ``select_agent(id)`` switches to another configured agent: the running turn is stopped,
  a new conversation starts (``conversation``) and ``init`` names the new current agent.
  ``on_agent_changed`` (the app's D-Bus state ``agent``) is called after every change. An
  unknown id is refused and ``init`` is sent again so the page shows the current agent;
- the session's config options (ACP ``configOptions``) go to the page as ``config_options
  {options}`` when a session is created, when the agent reports a change and after
  ``set_option``. Only ``select`` options with well-formed fields are passed on (flat or
  grouped values); the page shows the first one with ``category == "model"``;
- ``set_option(config_id, value)`` accepts only an option and value the session offered and
  forwards it to ``backend.set_option`` (ACP ``session/set_config_option``); the answer
  updates ``config_options``. On failure ``config_options`` is sent unchanged (the page
  shows the old value again) followed by a ``notice``.

This module must not import GTK.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app import strings
from app.backends.base import (
    Backend,
    BackendError,
    ConfigOptions,
    ContentPart,
    Done,
    Error,
    PermissionRequest,
    RestartLimitError,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolUpdate,
    event_to_dict,
)
from app.config import Agent, Config

log = logging.getLogger(__name__)

DEFAULT_AGENT_ENV = "AI_PANEL_DEFAULT_AGENT"
# How long a cancelled turn may take to end before the controller gives up on it.
CANCEL_TIMEOUT_S = 5.0
UNFINISHED_TOOL_STATUSES = frozenset({"pending", "in_progress"})
MAX_AUTH_METHODS = 20
# Bounds for config options passed to the page (they come from the agent).
MAX_CONFIG_OPTIONS = 32
MAX_OPTION_VALUES = 500
MAX_OPTION_ID_LENGTH = 256
MAX_OPTION_TEXT_LENGTH = 500

type UiEvent = dict[str, Any]
type BackendFactory = Callable[[Agent], Backend]


class UiSink(Protocol):
    def dispatch(self, event: UiEvent) -> None: ...


def choose_agent(config: Config, override: str | None = None) -> str | None:
    """``override`` (``AI_PANEL_DEFAULT_AGENT``) if it names a valid agent, then
    ``default_agent``, then the first valid agent; ``None`` when there is none."""
    if override:
        if override in config.agents:
            return override
        log.warning("%s=%r is not a valid agent, ignored", DEFAULT_AGENT_ENV, override)
    if config.default_agent in config.agents:
        return config.default_agent
    return next(iter(config.agents), None)


def resolve_theme(setting: str, system_dark: bool) -> str:
    """``chat.theme`` (``system``/``light``/``dark``) → the theme the page shows."""
    if setting in ("light", "dark"):
        return setting
    return "dark" if system_dark else "light"


def _error(message: str, kind: str = "other") -> UiEvent:
    return {"type": "error", "message": message, "kind": kind}


def _done(stop_reason: str) -> UiEvent:
    return {"type": "done", "stop_reason": stop_reason}


def _auth_method_text(method: Any) -> str | None:
    if not isinstance(method, dict):
        return None
    name = method.get("name") if isinstance(method.get("name"), str) else None
    name = name or (method.get("id") if isinstance(method.get("id"), str) else None)
    if not name:
        return None
    description = method.get("description")
    if isinstance(description, str) and description.strip():
        return f"{name}: {description}"
    return name


def error_event(error: Error, *, blocked: bool = False) -> UiEvent:
    """The chat message for a backend ``Error`` (texts from ``app/strings.py``).

    ``crashed``: the stderr tail goes to ``stderr`` (shown collapsed) and is cut from the
    message. ``auth``: the agent's login methods and a hint to log in in a terminal.
    ``blocked``: the agent will not be restarted in this conversation (restart limit)."""
    kind = error.kind if error.kind in strings.CHAT_ERROR_TITLES else "other"
    message = error.message
    stderr = error.stderr or None
    if stderr is not None:
        suffix = "\n" + strings.ACP_STDERR_TAIL.format(stderr=stderr)
        if message.endswith(suffix):
            message = message[: -len(suffix)]
    auth_methods: list[str] | None = None
    methods_label: str | None = None
    if kind == "auth":
        message = strings.CHAT_AUTH_MESSAGE
        texts = (_auth_method_text(m) for m in error.auth_methods or [])
        auth_methods = [text for text in texts if text][:MAX_AUTH_METHODS]
        methods_label = strings.CHAT_AUTH_METHODS if auth_methods else strings.CHAT_AUTH_NO_METHODS
    hint = strings.CHAT_RESTART_LIMIT_HINT if blocked else strings.CHAT_ERROR_HINTS.get(kind)
    return {
        "type": "error",
        "kind": kind,
        "title": strings.CHAT_ERROR_TITLES[kind],
        "message": message,
        "hint": hint,
        "stderr": stderr,
        "stderr_label": strings.CHAT_STDERR_LABEL if stderr is not None else None,
        "auth_methods": auth_methods,
        "methods_label": methods_label,
        "blocked": blocked,
    }


def _option_id(value: Any) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= MAX_OPTION_ID_LENGTH else None


def _option_text(value: Any) -> str | None:
    return value[:MAX_OPTION_TEXT_LENGTH] if isinstance(value, str) and value else None


def _select_value(item: Any) -> UiEvent | None:
    if not isinstance(item, dict):
        return None
    value = _option_id(item.get("value"))
    if value is None:
        return None
    entry: UiEvent = {"value": value, "name": _option_text(item.get("name")) or value}
    description = _option_text(item.get("description"))
    if description is not None:
        entry["description"] = description
    return entry


def _select_values(items: Any, budget: int) -> list[UiEvent]:
    if not isinstance(items, list):
        return []
    values = [entry for entry in map(_select_value, items) if entry is not None]
    return values[:budget]


def _normalize_option(option: Any) -> UiEvent | None:
    """One ACP ``SessionConfigOption`` of type ``select`` in the form the page reads, or
    ``None`` when it is not a usable select (other types are ignored, as ACP asks)."""
    if not isinstance(option, dict) or option.get("type") != "select":
        return None
    option_id = _option_id(option.get("id"))
    current = _option_id(option.get("currentValue"))
    items = option.get("options")
    if option_id is None or current is None or not isinstance(items, list):
        return None
    budget = MAX_OPTION_VALUES
    values: list[UiEvent] = []
    # ACP: either a flat list of values or a list of groups, never mixed.
    if any(isinstance(item, dict) and "group" in item for item in items):
        for item in items:
            if not isinstance(item, dict) or _option_id(item.get("group")) is None:
                continue
            group_values = _select_values(item.get("options"), budget)
            if group_values:
                budget -= len(group_values)
                values.append(
                    {
                        "group": item["group"],
                        "name": _option_text(item.get("name")) or item["group"],
                        "options": group_values,
                    }
                )
    else:
        values = _select_values(items, budget)
    if not values:
        return None
    normalized: UiEvent = {
        "id": option_id,
        "name": _option_text(option.get("name")) or option_id,
        "category": _option_id(option.get("category")),
        "type": "select",
        "currentValue": current,
        "options": values,
    }
    description = _option_text(option.get("description"))
    if description is not None:
        normalized["description"] = description
    return normalized


def normalize_config_options(options: Any) -> list[UiEvent]:
    """The usable ``select`` options of an ACP ``configOptions`` list, in the agent's order."""
    if not isinstance(options, list):
        return []
    result = [entry for entry in map(_normalize_option, options) if entry is not None]
    return result[:MAX_CONFIG_OPTIONS]


def option_values(option: UiEvent) -> set[str]:
    """Every value of a normalized select option (also inside groups)."""
    values: set[str] = set()
    for item in option["options"]:
        if "group" in item:
            values.update(value["value"] for value in item["options"])
        else:
            values.add(item["value"])
    return values


@dataclass(eq=False)
class _Turn:
    generation: int
    task: asyncio.Task[None] | None = None
    # Ends the turn if the backend does not confirm a cancel in time; stopped by _finish.
    watchdog: asyncio.Task[None] | None = None
    session_id: str | None = None
    cancel_requested: bool = False
    # Set once the closing ``done``/``error`` went to the UI; nothing is dispatched after it.
    finished: bool = False
    text: list[str] = field(default_factory=list)
    thinking: list[str] = field(default_factory=list)
    # Tool calls of the turn by id, in the stored form {"id", "title", "status", "input",
    # "output"} (PLAN §11.3); insertion order is the order of the calls.
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Unanswered permission requests of the turn: request id → the option ids offered.
    permissions: dict[str, frozenset[str]] = field(default_factory=dict)


class ChatController:
    def __init__(
        self,
        config: Config,
        ui_sink: UiSink,
        backend_factory: BackendFactory,
        *,
        default_agent: str | None = None,
        system_dark: Callable[[], bool] | None = None,
        cancel_timeout_s: float = CANCEL_TIMEOUT_S,
        on_agent_changed: Callable[[str | None], None] | None = None,
    ) -> None:
        self.config = config
        self._on_agent_changed = on_agent_changed
        self._cancel_timeout_s = cancel_timeout_s
        # Whether the desktop prefers dark (``Adw.StyleManager.dark`` in the app).
        self._system_dark = system_dark or (lambda: False)
        self._ui = ui_sink
        self._factory = backend_factory
        self.agent_id = choose_agent(config, default_agent)
        # The conversation in memory: {"role", "parts", "stop_reason"?} (PLAN §11.3).
        self.messages: list[dict[str, Any]] = []
        self._backend: Backend | None = None
        self._session_id: str | None = None
        self._session_task: asyncio.Task[str] | None = None
        # Bumped by new_chat(): results of an older conversation are dropped.
        self._generation = 0
        self._turn: _Turn | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        # Shown as ``notice`` when the next session of this conversation is created: the
        # previous one died with the agent (or was given up on after a cancel timeout).
        self._lost_notice: str | None = None
        # The agent hit the restart limit: no ``send`` until ``new_chat``.
        self._blocked = False
        # Normalized config options of the current session (``normalize_config_options``).
        self._options: list[UiEvent] = []
        if self.agent_id is not None:
            log.info("agent: %s", self.agent_id)
        else:
            log.info("no valid agent configured")

    # -- state -----------------------------------------------------------------------------

    @property
    def agent(self) -> Agent | None:
        return self.config.agents.get(self.agent_id) if self.agent_id is not None else None

    @property
    def busy(self) -> bool:
        return self._turn is not None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def blocked(self) -> bool:
        return self._blocked

    @property
    def config_options(self) -> list[UiEvent]:
        return list(self._options)

    @property
    def agents(self) -> list[tuple[str, str]]:
        """(id, name) of every valid agent, in configuration order (D-Bus state ``agents``)."""
        return [(agent.id, agent.name) for agent in self.config.agents.values()]

    @property
    def theme(self) -> str:
        return resolve_theme(self.config.chat.theme, bool(self._system_dark()))

    def init_event(self) -> UiEvent:
        return {
            "type": "init",
            "agents": [
                {"id": agent.id, "name": agent.name, "type": agent.type}
                for agent in self.config.agents.values()
            ],
            "current": self.agent_id,
            "config_errors": [
                {"path": error.path, "message": error.message, "line": error.line}
                for error in self.config.errors
            ],
            "theme": self.theme,
            "font_size": self.config.chat.font_size,
        }

    # -- UI messages -----------------------------------------------------------------------

    def ready(self) -> None:
        """The page (re)loaded: send it the agents and the configuration problems."""
        self._dispatch(self.init_event())

    def refresh_theme(self) -> None:
        """The desktop switched between light and dark: send ``init`` with the new theme."""
        log.debug("theme: %s", self.theme)
        self._dispatch(self.init_event())

    def send(self, text: str, images: list[ContentPart] | None = None) -> None:
        """Start a turn; answered with ``turn_start`` … ``done``/``error`` or only ``error``."""
        if self._turn is not None:
            log.warning("send rejected: a turn is already running")
            self._dispatch(_error(strings.CTRL_TURN_RUNNING))
            return
        if not text.strip() and not images:
            self._dispatch(_error(strings.CTRL_EMPTY_PROMPT))
            return
        agent = self.agent
        if agent is None:
            self._dispatch(_error(strings.CTRL_NO_AGENT))
            return
        if self._blocked:
            log.warning("send rejected: the agent hit its restart limit")
            self._dispatch(error_event(Error(strings.CTRL_BLOCKED, "crashed"), blocked=True))
            return
        try:
            backend = self._get_backend(agent)
        except NotImplementedError:
            log.warning("agent %s of type %s is not supported yet", agent.id, agent.type)
            self._dispatch(
                _error(strings.CTRL_AGENT_UNSUPPORTED.format(name=agent.name, type=agent.type))
            )
            return

        prompt: list[ContentPart] = [{"type": "text", "text": text}, *(images or [])]
        self.messages.append({"role": "user", "parts": prompt})
        turn = _Turn(self._generation)
        self._turn = turn
        self._dispatch({"type": "turn_start"})
        turn.task = self._spawn(self._run_turn(turn, backend, prompt), "chat-turn")

    def cancel(self) -> None:
        """Stop the running turn. Further calls until the turn ends do nothing."""
        turn = self._turn
        if turn is None or turn.cancel_requested:
            return
        turn.cancel_requested = True
        log.info("cancel requested")
        self._cancel_tools(turn)
        if turn.session_id is None:
            # No prompt was sent yet (the session is still being created): end the turn now.
            # The session creation itself goes on and is reused by the next turn.
            self._finish(turn, _done("cancelled"))
            if turn.task is not None:
                turn.task.cancel()
            return
        backend = self._backend
        if backend is not None:
            self._spawn(backend.cancel(turn.session_id), "chat-cancel")
        turn.watchdog = self._spawn(self._cancel_watchdog(turn), "chat-cancel-watchdog")

    def permission(self, request_id: str, option_id: str | None) -> None:
        """The user answered the permission dialog; ``None`` rejects the request.

        Only open requests of the running turn are answered, each at most once. An option
        the agent did not offer is treated as a rejection (the page is not trusted)."""
        turn = self._turn
        options = turn.permissions.pop(request_id, None) if turn is not None else None
        if turn is None or options is None or turn.finished:
            log.warning("permission answer for unknown request dropped")
            return
        if option_id is not None and option_id not in options:
            log.warning("permission answer with an unknown option, rejecting")
            option_id = None
        backend = self._backend
        if backend is None:
            log.debug("permission %s answered without a backend, dropped", request_id)
            return
        log.info("permission %s answered: %s", request_id, option_id or "rejected")
        try:
            backend.respond_permission(request_id, option_id)
        except Exception:
            log.exception("answering permission request %s failed", request_id)

    def select_agent(self, agent_id: str) -> bool:
        """Make ``agent_id`` the current agent and start a new conversation with it.

        Returns whether ``agent_id`` is now the current agent. Choosing the current agent
        again changes nothing."""
        if agent_id not in self.config.agents:
            log.warning("unknown agent %r not selected", agent_id[:64])
            self._dispatch(self.init_event())  # the page shows the current agent again
            return False
        if agent_id == self.agent_id:
            return True
        log.info("agent selected: %s", agent_id)
        self.agent_id = agent_id
        # The previous agent keeps its process (one per agent); this conversation uses the
        # new agent's backend from the next send on.
        self._backend = None
        self.new_chat()
        self._dispatch(self.init_event())
        if self._on_agent_changed is not None:
            try:
                self._on_agent_changed(agent_id)
            except Exception:
                log.exception("agent change callback failed")
        return True

    def set_option(self, config_id: str, value: str) -> None:
        """Change a config option of the current session (e.g. the model).

        Only an option and a value the session offered are forwarded; anything else is
        answered with the unchanged ``config_options`` so the page shows the real value."""
        option = next((o for o in self._options if o["id"] == config_id), None)
        session_id = self._session_id
        backend = self._backend
        if option is None or session_id is None or backend is None:
            log.warning("set_option for an unknown option dropped")
            self._dispatch_options()
            return
        if value not in option_values(option):
            log.warning("set_option %s with a value the agent did not offer dropped", config_id)
            self._dispatch_options()
            return
        if value == option["currentValue"]:
            self._dispatch_options()
            return
        log.info("option %s: %s", config_id, value)
        self._spawn(
            self._apply_option(backend, session_id, self._generation, option, value),
            "chat-set-option",
        )

    def new_chat(self) -> None:
        """Forget the conversation; the next ``send`` creates a new session."""
        log.info("new chat")
        turn = self._turn
        if turn is not None:
            turn.cancel_requested = True
            self._finish(turn, _done("cancelled"))
            if turn.task is not None:
                # Stops the iteration; the backend then tells the agent to cancel the turn.
                turn.task.cancel()
        self._generation += 1
        self._session_id = None
        self._session_task = None
        self._lost_notice = None
        self._blocked = False
        # The page drops its option selectors with the conversation.
        self._options = []
        self.messages = []
        self._dispatch({"type": "conversation", "id": None, "messages": []})

    async def close(self) -> None:
        """Stop the running turn and pending work (application quit)."""
        turn = self._turn
        if turn is not None:
            self._finish(turn, _done("cancelled"))
        tasks = [task for task in self._tasks if not task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # -- turn ------------------------------------------------------------------------------

    def _get_backend(self, agent: Agent) -> Backend:
        if self._backend is None:
            self._backend = self._factory(agent)
        return self._backend

    async def _ensure_session(self, backend: Backend) -> str:
        if self._session_id is not None:
            return self._session_id
        if self._session_task is None:
            self._session_task = self._spawn(
                self._create_session(backend, self._generation), "chat-session"
            )
        # Shielded: cancelling a turn must not abort a half-started agent.
        return await asyncio.shield(self._session_task)

    async def _create_session(self, backend: Backend, generation: int) -> str:
        try:
            session_id = await backend.new_session()
        except BaseException:
            if generation == self._generation:
                self._session_task = None  # the next turn tries again
            raise
        if generation == self._generation:
            self._session_id = session_id
            self._session_task = None
            try:
                options = backend.config_options(session_id)
            except Exception:
                log.exception("reading the config options of session %s failed", session_id)
                options = []
            if options or self._options:
                self._set_options(options)
        return session_id

    async def _apply_option(
        self, backend: Backend, session_id: str, generation: int, option: UiEvent, value: str
    ) -> None:
        reason: str | None = None
        options: Any = None
        try:
            options = await backend.set_option(session_id, option["id"], value)
            if options is None:
                options = backend.config_options(session_id)
        except BackendError as exc:
            log.warning("setting option %s failed: %s", option["id"], exc.event.message)
            reason = exc.event.message
        except Exception:
            log.exception("setting option %s failed", option["id"])
            reason = strings.CTRL_UNEXPECTED
        if generation != self._generation or session_id != self._session_id:
            return  # another conversation or session by now: its options are not these
        if reason is not None:
            self._dispatch_options()
            self._dispatch(
                {
                    "type": "notice",
                    "kind": "option_failed",
                    "text": strings.CTRL_OPTION_FAILED.format(name=option["name"], reason=reason),
                }
            )
            return
        self._set_options(options)

    def _set_options(self, options: Any) -> None:
        self._options = normalize_config_options(options)
        self._dispatch_options()

    def _dispatch_options(self) -> None:
        self._dispatch({"type": "config_options", "options": list(self._options)})

    def _drop_options(self) -> None:
        """The session is gone: its selectors are hidden until the next session."""
        if self._options:
            self._set_options([])

    async def _run_turn(self, turn: _Turn, backend: Backend, prompt: list[ContentPart]) -> None:
        final: UiEvent
        try:
            final = await self._drive(turn, backend, prompt)
        except asyncio.CancelledError:
            self._finish(turn, _done("cancelled"))
            raise
        except RestartLimitError as exc:
            log.warning("agent restart limit reached, conversation blocked until new chat")
            if turn.generation == self._generation:
                self._blocked = True
            final = error_event(exc.event, blocked=True)
        except BackendError as exc:
            final = error_event(exc.event)
        except Exception:
            log.exception("turn failed")
            final = _error(strings.CTRL_UNEXPECTED)
        self._finish(turn, final)

    async def _drive(self, turn: _Turn, backend: Backend, prompt: list[ContentPart]) -> UiEvent:
        fresh = self._session_id is None
        session_id = await self._ensure_session(backend)
        turn.session_id = session_id
        if fresh and self._lost_notice is not None and turn.generation == self._generation:
            log.info("new session after the previous one was lost")
            self._emit(turn, {"type": "notice", "kind": "context_lost", "text": self._lost_notice})
            self._lost_notice = None
        if turn.cancel_requested:
            return _done("cancelled")
        events = backend.send(session_id, prompt)
        try:
            async for event in events:
                if isinstance(event, TextDelta):
                    turn.text.append(event.text)
                    self._emit(turn, {"type": "text_delta", "text": event.text})
                elif isinstance(event, ThinkingDelta):
                    if event.text:
                        turn.thinking.append(event.text)
                        self._emit(turn, {"type": "thinking_delta", "text": event.text})
                elif isinstance(event, ToolCall):
                    self._emit(turn, _record_tool_call(turn, event))
                elif isinstance(event, ToolUpdate):
                    update = _record_tool_update(turn, event)
                    if update is None:
                        log.debug("update of unknown tool call dropped")
                    else:
                        self._emit(turn, update)
                elif isinstance(event, Done):
                    return _done(event.stop_reason)
                elif isinstance(event, ConfigOptions):
                    if turn.generation == self._generation and self._session_id == session_id:
                        self._set_options(event.options)
                elif isinstance(event, Error):
                    if event.kind == "crashed" and self._session_id == session_id:
                        self._session_id = None  # the session died with the process
                        self._lost_notice = strings.CTRL_AGENT_RESTARTED
                        self._drop_options()
                    return error_event(event)
                elif isinstance(event, PermissionRequest):
                    turn.permissions[event.request_id] = frozenset(o.id for o in event.options)
                    log.info("permission request %s waits for the user", event.request_id)
                    self._emit(turn, event_to_dict(event))
                else:
                    log.debug("event %s not shown yet", event.TYPE)
        finally:
            aclose = getattr(events, "aclose", None)
            if aclose is not None:
                await aclose()
        return _error(strings.CTRL_TURN_ENDED)

    def _emit(self, turn: _Turn, event: UiEvent) -> None:
        if not turn.finished:
            self._dispatch(event)

    def _finish(self, turn: _Turn, final: UiEvent) -> None:
        """Send the closing event of ``turn`` once and record the reply."""
        if turn.finished:
            return
        if final["type"] == "done" and final.get("stop_reason") == "cancelled":
            self._cancel_tools(turn)
        turn.finished = True
        watchdog = turn.watchdog
        if watchdog is not None and watchdog is not _current_task():
            watchdog.cancel()
        # The backend answers open requests of an ended turn itself (ACP: cancelled).
        turn.permissions.clear()
        if self._turn is turn:
            self._turn = None
        if turn.generation == self._generation:
            message: dict[str, Any] = {
                "role": "assistant",
                "parts": [{"type": "text", "text": "".join(turn.text)}],
            }
            if turn.thinking:
                message["thinking"] = "".join(turn.thinking)
            if turn.tools:
                message["tools"] = list(turn.tools.values())
            if final["type"] == "done":
                message["stop_reason"] = final["stop_reason"]
            else:
                message["stop_reason"] = "error"
                message["error"] = {"message": final.get("message"), "kind": final.get("kind")}
            self.messages.append(message)
        self._dispatch(final)

    def _cancel_tools(self, turn: _Turn) -> None:
        """Mark the unfinished tool calls of ``turn`` as ``cancelled`` (stored and in the UI)."""
        for tool in turn.tools.values():
            if tool["status"] in UNFINISHED_TOOL_STATUSES:
                tool["status"] = "cancelled"
                self._emit(turn, {"type": "tool_update", "id": tool["id"], "status": "cancelled"})

    async def _cancel_watchdog(self, turn: _Turn) -> None:
        """End a cancelled turn whose backend does not confirm the cancel in time."""
        await asyncio.sleep(self._cancel_timeout_s)
        if turn.finished:
            return
        log.warning(
            "the agent did not end the cancelled turn within %g s, giving up on it",
            self._cancel_timeout_s,
        )
        if turn.generation == self._generation and self._session_id == turn.session_id:
            # The agent may still be working on the old prompt: do not send it another one
            # in the same session.
            self._session_id = None
            self._lost_notice = strings.CTRL_SESSION_ABANDONED
            self._drop_options()
        self._finish(turn, _done("cancelled"))
        if turn.task is not None:
            turn.task.cancel()  # closes the event iterator; the backend drops the turn

    # -- helpers ---------------------------------------------------------------------------

    def _dispatch(self, event: UiEvent) -> None:
        try:
            self._ui.dispatch(event)
        except Exception:
            log.exception("dispatching %s to the UI failed", event.get("type"))

    def _spawn[T](self, coro: Any, name: str) -> asyncio.Task[T]:
        task: asyncio.Task[T] = asyncio.get_running_loop().create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None and task.get_name() == "chat-cancel":
            log.warning("cancel failed: %s", exc)


def _current_task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:  # no running event loop
        return None


def _record_tool_call(turn: _Turn, event: ToolCall) -> UiEvent:
    """Store a new tool call of ``turn`` and return its ``tool_call`` UI event.

    A repeated ``tool_call`` with a known id replaces the stored call (the UI updates the
    existing card the same way)."""
    turn.tools[event.id] = {
        "id": event.id,
        "title": event.title,
        "status": event.status or "pending",
        "input": event.raw_input,
        "output": event.content,
    }
    return event_to_dict(event)


def _record_tool_update(turn: _Turn, event: ToolUpdate) -> UiEvent | None:
    """Apply ``event`` to the stored tool call; ``None`` when the id is unknown.

    The UI event carries only the fields the agent sent (``None`` means unchanged)."""
    tool = turn.tools.get(event.id)
    if tool is None:
        return None
    ui: UiEvent = {"type": "tool_update", "id": event.id}
    for name, key in (
        ("status", "status"),
        ("title", "title"),
        ("raw_input", "input"),
        ("content", "output"),
    ):
        value = getattr(event, name)
        if value is not None:
            ui[name] = value
            tool[key] = value
    return ui


def default_agent_override(environ: Mapping[str, str]) -> str | None:
    return environ.get(DEFAULT_AGENT_ENV) or None
