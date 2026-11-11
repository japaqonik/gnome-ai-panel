"""Generic ACP client: one agent process from ``config.toml``, many sessions (FR-15–17, FR-29,
FR-46, FR-50).

``AcpBackend(agent, mcp_servers)`` implements ``Backend`` (``base.py``) over
``JsonRpcConnection`` (``jsonrpc.py``):

- the process starts lazily on the first ``new_session()`` (or ``start()``): argv is
  ``command`` + ``args`` without a shell, the environment is the session environment plus the
  resolved ``env`` entries (``app/secrets.resolve_env``), ``cwd`` is created with mode 0700.
  It runs in its own process group so that ``close()`` also stops its children;
- ``initialize`` (protocol version 1, ``fs``/``terminal`` capabilities off) must answer within
  ``startup_timeout_s``; any other protocol version is rejected (``Error`` kind ``protocol``);
- ``new_session()`` sends ``session/new`` with the absolute ``cwd``, the agent's ``mcp``
  servers (``env`` as ``[{name, value}]``), ``session_meta`` as ``_meta`` and
  ``system_prompt`` as ``systemPrompt`` (mode ``append``) when the agent advertises
  ``agentCapabilities.sessionCapabilities.systemPrompt``;
- ``send()`` runs ``session/prompt`` and turns ``session/update`` notifications of that
  session into events (``map_session_update``); ``session/request_permission`` becomes a
  ``PermissionRequest`` answered through ``respond_permission``;
- when the process ends during a turn, the turn ends with ``Error`` kind ``crashed`` (exit
  code and the last 20 stderr lines); the next ``new_session()`` starts a new process, at most
  ``RESTART_LIMIT`` times per ``RESTART_WINDOW_S``;
- ``close()``: SIGTERM, after ``TERM_GRACE_S`` SIGKILL.

Failures of ``start``/``new_session``/``set_option`` raise ``BackendError`` carrying the
``Error`` event; ``send`` never raises for agent problems, it yields ``Error`` instead.

Secret values never reach the log: the agent environment is not logged, the JSON-RPC log
redacts ``env`` keys (MCP servers) and resolved secrets are registered with the log filter.
This module does not import GTK.
"""

import asyncio
import contextlib
import itertools
import logging
import os
import shutil
import signal
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from app import __version__, strings
from app.backends.base import (
    BackendError,
    ConfigOptions,
    ContentPart,
    Done,
    Error,
    Event,
    PermissionOption,
    PermissionRequest,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolUpdate,
    Usage,
)
from app.backends.jsonrpc import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    ConnectionClosed,
    JsonRpcConnection,
    JsonRpcError,
)
from app.config import AcpAgent, McpServer
from app.secrets import PromptCallback, SecretError, SecretStore, resolve_env

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
CLIENT_INFO = {"name": "gnome-ai-panel", "title": "GNOME AI Panel", "version": __version__}
CLIENT_CAPABILITIES = {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}
AUTH_REQUIRED_CODE = -32000  # ACP: "Authentication required"

STDERR_TAIL_LINES = 20
STDERR_LINE_LIMIT = 2000
STDERR_READ_CHUNK = 64 * 1024
TERM_GRACE_S = 3.0
EXIT_WAIT_S = 2.0
RESTART_LIMIT = 3
RESTART_WINDOW_S = 60.0

_CANCELLED_OUTCOME = {"outcome": "cancelled"}
_TURN_END = object()


# -- session/update → events -----------------------------------------------------------------


def _text_of(content: Any) -> str | None:
    if isinstance(content, dict) and content.get("type") == "text":
        text = content.get("text")
        if isinstance(text, str):
            return text
    return None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def map_session_update(update: Any) -> Event | None:
    """Event for one ``params.update`` of ``session/update``; ``None`` for everything the
    panel does not show (unknown types, user message replay, plans, malformed updates)."""
    if not isinstance(update, dict):
        return None
    kind = update.get("sessionUpdate")
    if kind in ("agent_message_chunk", "agent_thought_chunk"):
        text = _text_of(update.get("content"))
        if text is None:
            return None
        return TextDelta(text) if kind == "agent_message_chunk" else ThinkingDelta(text)
    if kind == "tool_call":
        tool_id = update.get("toolCallId")
        if not isinstance(tool_id, str):
            return None
        return ToolCall(
            id=tool_id,
            title=_str_or_none(update.get("title")) or "",
            kind=_str_or_none(update.get("kind")),
            status=_str_or_none(update.get("status")),
            raw_input=update.get("rawInput"),
            content=update.get("content"),
        )
    if kind == "tool_call_update":
        tool_id = update.get("toolCallId")
        if not isinstance(tool_id, str):
            return None
        return ToolUpdate(
            id=tool_id,
            status=_str_or_none(update.get("status")),
            title=_str_or_none(update.get("title")),
            raw_input=update.get("rawInput"),
            content=update.get("content"),
        )
    if kind == "config_option_update":
        options = update.get("configOptions")
        if not isinstance(options, list):
            return None
        return ConfigOptions([o for o in options if isinstance(o, dict)])
    if kind == "usage_update":
        cost = update.get("cost") if isinstance(update.get("cost"), dict) else {}
        return Usage(
            used=_int_or_none(update.get("used")),
            size=_int_or_none(update.get("size")),
            cost_amount=_number_or_none(cost.get("amount")),
            cost_currency=_str_or_none(cost.get("currency")),
        )
    return None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def parse_permission_options(options: Any) -> list[PermissionOption]:
    result: list[PermissionOption] = []
    if not isinstance(options, list):
        return result
    for option in options:
        if not isinstance(option, dict) or not isinstance(option.get("optionId"), str):
            continue
        name = _str_or_none(option.get("name")) or option["optionId"]
        result.append(PermissionOption(option["optionId"], name, _str_or_none(option.get("kind"))))
    return result


def reject_outcome(options: list[PermissionOption]) -> dict[str, Any]:
    """Outcome for "no" (``respond_permission(id, None)``): the agent's reject option, or
    ``cancelled`` when it offers none."""
    for wanted in ("reject_once", "reject_always"):
        for option in options:
            if option.kind == wanted:
                return {"outcome": "selected", "optionId": option.id}
    return dict(_CANCELLED_OUTCOME)


def is_auth_error(exc: JsonRpcError) -> bool:
    if exc.code == AUTH_REQUIRED_CODE:
        return True
    text = f"{exc.message} {exc.data!r}".lower()
    return "auth_required" in text


def format_auth_methods(methods: list[dict[str, Any]]) -> str:
    parts = []
    for method in methods:
        name = _str_or_none(method.get("name")) or _str_or_none(method.get("id")) or "?"
        description = _str_or_none(method.get("description"))
        parts.append(f"{name} ({description})" if description else name)
    return "; ".join(parts) if parts else strings.ACP_AUTH_NO_METHODS


# -- internal state ----------------------------------------------------------------------------


@dataclass
class _Turn:
    queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    cancelled: bool = False


@dataclass
class _Process:
    proc: asyncio.subprocess.Process
    conn: JsonRpcConnection | None = None
    stderr_tail: deque[str] = field(default_factory=lambda: deque(maxlen=STDERR_TAIL_LINES))
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    stopping: bool = False

    @property
    def alive(self) -> bool:
        return (
            self.proc.returncode is None
            and self.conn is not None
            and not self.conn.closed
            and not self.stopping
        )


@dataclass
class _Session:
    id: str
    process: _Process
    turn: _Turn | None = None


@dataclass
class _Permission:
    session_id: str
    options: list[PermissionOption]
    future: asyncio.Future[dict[str, Any]]


# -- backend -----------------------------------------------------------------------------------


class AcpBackend:
    def __init__(
        self,
        agent: AcpAgent,
        mcp_servers: Mapping[str, McpServer] | None = None,
        *,
        store: SecretStore | None = None,
        prompt_cb: PromptCallback | None = None,
    ) -> None:
        self.agent = agent
        self.name = agent.name
        self._mcp = dict(mcp_servers or {})
        self._store = store
        self._prompt_cb = prompt_cb
        self._proc: _Process | None = None
        self._start_lock = asyncio.Lock()
        self._sessions: dict[str, _Session] = {}
        self._lost_sessions: set[str] = set()
        self._permissions: dict[str, _Permission] = {}
        self._permission_ids = itertools.count(1)
        self._restarts: deque[float] = deque()
        self._crashed = False
        self._pending_config: tuple[AcpAgent, dict[str, McpServer]] | None = None
        self._background: set[asyncio.Task[Any]] = set()
        self._closed = False
        # Filled by a successful ``initialize``.
        self.protocol_version: int | None = None
        self.agent_info: dict[str, Any] | None = None
        self.agent_capabilities: dict[str, Any] = {}
        self.auth_methods: list[dict[str, Any]] = []

    # -- public API ----------------------------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pid(self) -> int | None:
        """PID of the running agent process (tests, diagnostics)."""
        if self._proc is None or self._proc.proc.returncode is not None:
            return None
        return self._proc.proc.pid

    async def start(self) -> None:
        """Start the process and run ``initialize`` unless it already runs."""
        async with self._start_lock:
            await self._ensure_process()

    def reconfigure(self, agent: AcpAgent, mcp_servers: Mapping[str, McpServer] | None) -> None:
        """Use a changed configuration from the next ``new_session()`` on (the process is
        restarted then; a running turn is not interrupted)."""
        mcp = dict(mcp_servers or {})
        if agent == self.agent and self._relevant_mcp(agent, mcp) == self._relevant_mcp(
            self.agent, self._mcp
        ):
            self._pending_config = None
            return
        self._pending_config = (agent, mcp)

    async def new_session(self) -> str:
        async with self._start_lock:
            process = await self._ensure_process()
        params = await self._session_params()
        result = await self._request(
            process,
            "session/new",
            params,
            timeout_message=strings.ACP_SESSION_TIMEOUT.format(
                timeout=self.agent.startup_timeout_s
            ),
        )
        session_id = result.get("sessionId") if isinstance(result, dict) else None
        if not isinstance(session_id, str) or not session_id:
            raise BackendError(
                Error(strings.ACP_BAD_RESPONSE.format(method="session/new"), "protocol")
            )
        self._sessions[session_id] = _Session(session_id, process)
        self._lost_sessions.discard(session_id)
        log.info("%s: session %s created", self.agent.id, session_id)
        return session_id

    async def send(self, session_id: str, prompt: list[ContentPart]) -> AsyncIterator[Event]:
        session = self._sessions.get(session_id)
        if session is None:
            if session_id in self._lost_sessions:
                yield Error(strings.ACP_SESSION_LOST, "crashed")
            else:
                yield Error(strings.ACP_UNKNOWN_SESSION.format(session_id=session_id), "other")
            return
        process = session.process
        if not process.alive or process.conn is None:
            yield Error(strings.ACP_SESSION_LOST, "crashed")
            return
        if session.turn is not None:
            yield Error(strings.ACP_TURN_RUNNING, "other")
            return

        turn = _Turn()
        session.turn = turn
        request = asyncio.create_task(
            process.conn.request(
                "session/prompt", {"sessionId": session_id, "prompt": list(prompt)}
            ),
            name=f"acp-{self.agent.id}-prompt",
        )
        # Updates are queued by the reader before the response resolves the request, so the
        # end marker always comes after every update of the turn.
        request.add_done_callback(lambda _: turn.queue.put_nowait(_TURN_END))
        try:
            while (item := await turn.queue.get()) is not _TURN_END:
                yield item
            yield await self._turn_result(process, turn, request)
        finally:
            session.turn = None
            self._cancel_permissions(session_id)
            if not request.done():
                # The consumer stopped early: stop the turn on the agent's side too.
                request.cancel()
                if process.alive and not turn.cancelled:
                    self._spawn_background(self._notify_cancel(process, session_id))

    def respond_permission(self, request_id: str, option_id: str | None) -> None:
        permission = self._permissions.get(request_id)
        if permission is None or permission.future.done():
            log.warning("%s: no pending permission request %s", self.agent.id, request_id)
            return
        if option_id is not None and any(o.id == option_id for o in permission.options):
            outcome = {"outcome": "selected", "optionId": option_id}
        else:
            if option_id is not None:
                log.warning("%s: unknown permission option %r, rejecting", self.agent.id, option_id)
            outcome = reject_outcome(permission.options)
        permission.future.set_result(outcome)

    async def cancel(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.turn is None:
            return
        session.turn.cancelled = True
        if session.process.alive:
            await self._notify_cancel(session.process, session_id)
        # ACP: pending permission requests of a cancelled turn are answered "cancelled".
        self._cancel_permissions(session_id)

    async def set_option(self, session_id: str, config_id: str, value: str) -> None:
        session = self._sessions.get(session_id)
        if session is None or not session.process.alive:
            raise BackendError(Error(strings.ACP_SESSION_LOST, "crashed"))
        await self._request(
            session.process,
            "session/set_config_option",
            {"sessionId": session_id, "configId": config_id, "value": value},
            timeout_message=None,
        )

    async def close(self) -> None:
        self._closed = True
        process, self._proc = self._proc, None
        for permission in list(self._permissions.values()):
            if not permission.future.done():
                permission.future.set_result(dict(_CANCELLED_OUTCOME))
        if process is not None:
            await self._stop_process(process, TERM_GRACE_S)
        for task in list(self._background):
            task.cancel()
        self._lost_sessions.update(self._sessions)
        self._sessions.clear()

    # -- process lifecycle ---------------------------------------------------------------------

    def _busy(self) -> bool:
        return any(s.turn is not None for s in self._sessions.values())

    async def _ensure_process(self) -> _Process:
        if self._closed:
            raise BackendError(Error(strings.ACP_CLOSED, "other"))
        if self._pending_config is not None and not self._busy():
            self.agent, self._mcp = self._pending_config
            self.name = self.agent.name
            self._pending_config = None
            if self._proc is not None:
                log.info("%s: configuration changed, restarting the agent", self.agent.id)
                old, self._proc = self._proc, None
                self._forget_sessions(old)
                await self._stop_process(old, TERM_GRACE_S)
            self._crashed = False
            self._restarts.clear()
        if self._proc is not None and self._proc.alive:
            return self._proc
        if self._proc is not None:
            old, self._proc = self._proc, None
            self._forget_sessions(old)
            await self._stop_process(old, 0)
        if self._crashed:
            self._check_restart_limit()
            log.info("%s: restarting the agent after a crash", self.agent.id)
        process = await self._spawn()
        try:
            await self._initialize(process)
        except BaseException:
            await self._stop_process(process, 0)
            raise
        self._proc = process
        self._crashed = False
        return process

    def _check_restart_limit(self) -> None:
        now = asyncio.get_running_loop().time()
        while self._restarts and now - self._restarts[0] > RESTART_WINDOW_S:
            self._restarts.popleft()
        if len(self._restarts) >= RESTART_LIMIT:
            raise BackendError(
                Error(
                    strings.ACP_RESTART_LIMIT.format(count=RESTART_LIMIT, window=RESTART_WINDOW_S),
                    "crashed",
                )
            )
        self._restarts.append(now)

    def _forget_sessions(self, process: _Process) -> None:
        for session_id, session in list(self._sessions.items()):
            if session.process is process:
                del self._sessions[session_id]
                self._lost_sessions.add(session_id)

    def _program(self, env: Mapping[str, str]) -> str:
        command = self.agent.command
        if "/" in command:
            return command  # app/config.py already expanded and absolutised it
        found = shutil.which(command, path=env.get("PATH", os.defpath))
        if found is None:
            raise BackendError(
                Error(strings.ACP_COMMAND_NOT_FOUND.format(command=command), "spawn")
            )
        return found

    async def _spawn(self) -> _Process:
        agent = self.agent
        try:
            extra = await resolve_env(agent, store=self._store, prompt_cb=self._prompt_cb)
        except SecretError as exc:
            raise BackendError(Error(strings.ACP_ENV_FAILED.format(reason=exc), "spawn")) from None
        env = dict(os.environ)
        env.update(extra)
        cwd = os.path.abspath(agent.cwd)
        try:
            os.makedirs(cwd, mode=0o700, exist_ok=True)
        except OSError as exc:
            raise BackendError(
                Error(strings.ACP_CWD_FAILED.format(path=cwd, reason=exc.strerror or exc), "spawn")
            ) from None
        program = self._program(env)
        try:
            proc = await asyncio.create_subprocess_exec(
                program,
                *agent.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                start_new_session=True,  # own process group: close() reaches its children
            )
        except FileNotFoundError:
            raise BackendError(
                Error(strings.ACP_COMMAND_NOT_FOUND.format(command=agent.command), "spawn")
            ) from None
        except OSError as exc:
            reason = exc.strerror or type(exc).__name__
            raise BackendError(
                Error(
                    strings.ACP_SPAWN_FAILED.format(command=agent.command, reason=reason), "spawn"
                )
            ) from None
        log.info("%s: started %s (pid %d) in %s", agent.id, program, proc.pid, cwd)

        process = _Process(proc)
        if proc.stdout is None or proc.stdin is None:  # cannot happen: PIPE above
            raise RuntimeError("agent stdio is not a pipe")
        process.conn = JsonRpcConnection(
            proc.stdout,
            proc.stdin,
            request_handler=lambda method, params: self._on_request(process, method, params),
            notification_handler=lambda method, params: self._on_notification(
                process, method, params
            ),
            name=f"acp:{agent.id}",
        )
        process.conn.start()
        process.tasks.append(asyncio.create_task(self._read_stderr(process)))
        process.tasks.append(asyncio.create_task(self._watch(process)))
        return process

    async def _initialize(self, process: _Process) -> None:
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": CLIENT_CAPABILITIES,
            "clientInfo": CLIENT_INFO,
        }
        timeout = self.agent.startup_timeout_s
        result = await self._request(
            process,
            "initialize",
            params,
            timeout_message=strings.ACP_STARTUP_TIMEOUT.format(timeout=timeout),
            exit_prefix=strings.ACP_EXITED_AT_START,
        )
        if not isinstance(result, dict):
            raise BackendError(
                Error(strings.ACP_BAD_RESPONSE.format(method="initialize"), "protocol")
            )
        version = result.get("protocolVersion")
        if version != PROTOCOL_VERSION or isinstance(version, bool):
            raise BackendError(
                Error(
                    strings.ACP_BAD_VERSION.format(version=version, supported=PROTOCOL_VERSION),
                    "protocol",
                )
            )
        self.protocol_version = PROTOCOL_VERSION
        info = result.get("agentInfo")
        self.agent_info = info if isinstance(info, dict) else None
        caps = result.get("agentCapabilities")
        self.agent_capabilities = caps if isinstance(caps, dict) else {}
        methods = result.get("authMethods")
        self.auth_methods = (
            [m for m in methods if isinstance(m, dict)] if isinstance(methods, list) else []
        )
        log.info(
            "%s: initialized, agent %s %s",
            self.agent.id,
            (self.agent_info or {}).get("name", "?"),
            (self.agent_info or {}).get("version", "?"),
        )

    async def _read_stderr(self, process: _Process) -> None:
        stream = process.proc.stderr
        if stream is None:
            return
        buffer = b""
        while True:
            chunk = await stream.read(STDERR_READ_CHUNK)
            if not chunk:
                break
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                self._stderr_line(process, line)
            if len(buffer) > STDERR_LINE_LIMIT:
                self._stderr_line(process, buffer)
                buffer = b""
        if buffer:
            self._stderr_line(process, buffer)

    def _stderr_line(self, process: _Process, raw: bytes) -> None:
        line = raw.rstrip(b"\r").decode(errors="replace")[:STDERR_LINE_LIMIT]
        process.stderr_tail.append(line)
        log.debug("%s stderr: %s", self.agent.id, line)

    async def _watch(self, process: _Process) -> None:
        code = await process.proc.wait()
        # A child holding stdout open would keep the connection alive: close it here so
        # that waiting requests fail now.
        if process.conn is not None:
            await process.conn.close()
        if not process.stopping and not self._closed:
            log.warning("%s: agent process exited with code %s", self.agent.id, code)
            self._crashed = True

    async def _stop_process(self, process: _Process, grace: float) -> None:
        process.stopping = True
        proc = process.proc
        if proc.returncode is None:
            _signal_group(proc.pid, signal.SIGTERM if grace > 0 else signal.SIGKILL)
            try:
                async with asyncio.timeout(grace if grace > 0 else EXIT_WAIT_S):
                    await proc.wait()
            except TimeoutError:
                log.warning("%s: agent did not stop after SIGTERM, killing it", self.agent.id)
                _signal_group(proc.pid, signal.SIGKILL)
                await proc.wait()
        if process.conn is not None:
            await process.conn.close()
        if proc.stdin is not None:
            proc.stdin.close()
        for task in process.tasks:
            if task is not asyncio.current_task():
                task.cancel()
        for task in process.tasks:
            if task is not asyncio.current_task():
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _exit_error(self, process: _Process, prefix: str | None = None) -> Error:
        """``Error`` kind ``crashed`` for a process whose connection ended."""
        proc = process.proc
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(EXIT_WAIT_S):
                await proc.wait()
        # Let the stderr reader take the last lines (the pipe closes with the process).
        if process.tasks:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                async with asyncio.timeout(1.0):
                    await asyncio.shield(process.tasks[0])
        self._crashed = True
        code = proc.returncode
        if code is None:
            message = strings.ACP_EXITED_UNKNOWN
        elif code < 0:
            message = strings.ACP_EXITED_SIGNAL.format(signal=_signal_name(-code))
        else:
            message = strings.ACP_EXITED.format(code=code)
        if prefix:
            message = f"{prefix} {message}"
        tail = "\n".join(process.stderr_tail)
        if tail:
            message += "\n" + strings.ACP_STDERR_TAIL.format(stderr=tail)
        return Error(message, "crashed", stderr=tail or None)

    # -- requests ------------------------------------------------------------------------------

    async def _request(
        self,
        process: _Process,
        method: str,
        params: Any,
        *,
        timeout_message: str | None,
        exit_prefix: str | None = None,
    ) -> Any:
        if process.conn is None:
            raise BackendError(Error(strings.ACP_CLOSED, "other"))
        timeout = self.agent.startup_timeout_s if timeout_message else None
        try:
            return await process.conn.request(method, params, timeout=timeout)
        except TimeoutError:
            raise BackendError(Error(timeout_message or method, "timeout")) from None
        except ConnectionClosed:
            if process.stopping or self._closed:
                raise BackendError(Error(strings.ACP_CLOSED, "other")) from None
            raise BackendError(await self._exit_error(process, exit_prefix)) from None
        except JsonRpcError as exc:
            raise BackendError(self._rpc_error(method, exc)) from None

    def _rpc_error(self, method: str, exc: JsonRpcError) -> Error:
        if is_auth_error(exc):
            return Error(
                strings.ACP_AUTH_REQUIRED.format(methods=format_auth_methods(self.auth_methods)),
                "auth",
                auth_methods=list(self.auth_methods),
            )
        return Error(
            strings.ACP_REQUEST_FAILED.format(method=method, reason=exc.message or exc.code),
            "protocol",
        )

    async def _turn_result(
        self, process: _Process, turn: _Turn, request: asyncio.Task[Any]
    ) -> Done | Error:
        try:
            result = request.result()
        except JsonRpcError as exc:
            if turn.cancelled:
                return Done("cancelled")
            return self._rpc_error("session/prompt", exc)
        except ConnectionClosed:
            if process.stopping or self._closed:
                return Error(strings.ACP_CLOSED, "other")
            return await self._exit_error(process)
        stop_reason = result.get("stopReason") if isinstance(result, dict) else None
        if not isinstance(stop_reason, str) or not stop_reason:
            log.warning("%s: session/prompt result without stopReason", self.agent.id)
            stop_reason = "cancelled" if turn.cancelled else "end_turn"
        return Done(stop_reason)

    async def _notify_cancel(self, process: _Process, session_id: str) -> None:
        if process.conn is None:
            return
        with contextlib.suppress(ConnectionClosed):
            await process.conn.notify("session/cancel", {"sessionId": session_id})

    def _spawn_background(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    @staticmethod
    def _relevant_mcp(agent: AcpAgent, mcp: Mapping[str, McpServer]) -> dict[str, McpServer]:
        return {mcp_id: mcp[mcp_id] for mcp_id in agent.mcp if mcp_id in mcp}

    async def _session_params(self) -> dict[str, Any]:
        agent = self.agent
        servers = []
        for mcp_id in agent.mcp:
            server = self._mcp.get(mcp_id)
            if server is None:
                log.warning("%s: MCP server %r is not configured, skipped", agent.id, mcp_id)
                continue
            try:
                env = await resolve_env(server, store=self._store, prompt_cb=self._prompt_cb)
            except SecretError as exc:
                raise BackendError(
                    Error(strings.ACP_MCP_ENV_FAILED.format(id=mcp_id, reason=exc), "spawn")
                ) from None
            command = server.command
            if "/" not in command:
                command = shutil.which(command) or command
            servers.append(
                {
                    "name": mcp_id,
                    "command": command,
                    "args": list(server.args),
                    "env": [{"name": k, "value": v} for k, v in env.items()],
                }
            )
        params: dict[str, Any] = {"cwd": os.path.abspath(agent.cwd), "mcpServers": servers}
        if agent.session_meta is not None:
            params["_meta"] = agent.session_meta
        if agent.system_prompt and self._supports_system_prompt():
            params["systemPrompt"] = {
                "mode": "append",
                "content": [{"type": "text", "text": agent.system_prompt}],
            }
        return params

    def _supports_system_prompt(self) -> bool:
        session_caps = self.agent_capabilities.get("sessionCapabilities")
        return isinstance(session_caps, dict) and isinstance(session_caps.get("systemPrompt"), dict)

    # -- incoming messages ---------------------------------------------------------------------

    def _on_notification(self, process: _Process, method: str, params: Any) -> None:
        if method != "session/update" or not isinstance(params, dict):
            log.debug("%s: ignoring notification %s", self.agent.id, method)
            return
        session = self._sessions.get(params.get("sessionId"))
        if session is None or session.process is not process or session.turn is None:
            log.debug("%s: session/update outside a turn ignored", self.agent.id)
            return
        event = map_session_update(params.get("update"))
        if event is not None:
            session.turn.queue.put_nowait(event)

    async def _on_request(self, process: _Process, method: str, params: Any) -> Any:
        if method != "session/request_permission":
            # fs/* and terminal/* are declared unsupported in initialize (NFR-2).
            raise JsonRpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "Invalid params")
        session = self._sessions.get(params.get("sessionId"))
        turn = session.turn if session is not None and session.process is process else None
        if turn is None or turn.cancelled:
            return {"outcome": dict(_CANCELLED_OUTCOME)}
        options = parse_permission_options(params.get("options"))
        tool = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
        request_id = f"perm-{next(self._permission_ids)}"
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._permissions[request_id] = _Permission(session.id, options, future)
        turn.queue.put_nowait(
            PermissionRequest(
                request_id=request_id,
                tool_call_id=_str_or_none(tool.get("toolCallId")),
                title=_str_or_none(tool.get("title")) or "",
                kind=_str_or_none(tool.get("kind")),
                raw_input=tool.get("rawInput"),
                options=options,
            )
        )
        try:
            return {"outcome": await future}
        finally:
            self._permissions.pop(request_id, None)

    def _cancel_permissions(self, session_id: str) -> None:
        for permission in list(self._permissions.values()):
            if permission.session_id == session_id and not permission.future.done():
                permission.future.set_result(dict(_CANCELLED_OUTCOME))


def _signal_group(pid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, sig)


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return str(number)
