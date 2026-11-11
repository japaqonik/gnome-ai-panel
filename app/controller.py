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
    ContentPart,
    Done,
    Error,
    PermissionRequest,
    TextDelta,
    event_to_dict,
)
from app.config import Agent, Config

log = logging.getLogger(__name__)

DEFAULT_AGENT_ENV = "AI_PANEL_DEFAULT_AGENT"

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


@dataclass(eq=False)
class _Turn:
    generation: int
    task: asyncio.Task[None] | None = None
    session_id: str | None = None
    cancel_requested: bool = False
    # Set once the closing ``done``/``error`` went to the UI; nothing is dispatched after it.
    finished: bool = False
    text: list[str] = field(default_factory=list)


class ChatController:
    def __init__(
        self,
        config: Config,
        ui_sink: UiSink,
        backend_factory: BackendFactory,
        *,
        default_agent: str | None = None,
        system_dark: Callable[[], bool] | None = None,
    ) -> None:
        self.config = config
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
        return session_id

    async def _run_turn(self, turn: _Turn, backend: Backend, prompt: list[ContentPart]) -> None:
        final: UiEvent
        try:
            final = await self._drive(turn, backend, prompt)
        except asyncio.CancelledError:
            self._finish(turn, _done("cancelled"))
            raise
        except BackendError as exc:
            final = event_to_dict(exc.event)
        except Exception:
            log.exception("turn failed")
            final = _error(strings.CTRL_UNEXPECTED)
        self._finish(turn, final)

    async def _drive(self, turn: _Turn, backend: Backend, prompt: list[ContentPart]) -> UiEvent:
        session_id = await self._ensure_session(backend)
        turn.session_id = session_id
        if turn.cancel_requested:
            return _done("cancelled")
        events = backend.send(session_id, prompt)
        try:
            async for event in events:
                if isinstance(event, TextDelta):
                    turn.text.append(event.text)
                    self._emit(turn, {"type": "text_delta", "text": event.text})
                elif isinstance(event, Done):
                    return _done(event.stop_reason)
                elif isinstance(event, Error):
                    if event.kind == "crashed" and self._session_id == session_id:
                        self._session_id = None  # the session died with the process
                    return event_to_dict(event)
                elif isinstance(event, PermissionRequest):
                    # The permission dialog comes in S4-T2; until then nothing is allowed.
                    log.warning("permission request %s rejected (no dialog yet)", event.request_id)
                    backend.respond_permission(event.request_id, None)
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
        turn.finished = True
        if self._turn is turn:
            self._turn = None
        if turn.generation == self._generation:
            message: dict[str, Any] = {
                "role": "assistant",
                "parts": [{"type": "text", "text": "".join(turn.text)}],
            }
            if final["type"] == "done":
                message["stop_reason"] = final["stop_reason"]
            else:
                message["stop_reason"] = "error"
                message["error"] = {"message": final.get("message"), "kind": final.get("kind")}
            self.messages.append(message)
        self._dispatch(final)

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


def default_agent_override(environ: Mapping[str, str]) -> str | None:
    return environ.get(DEFAULT_AGENT_ENV) or None
