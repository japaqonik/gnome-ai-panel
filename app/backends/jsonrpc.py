"""JSON-RPC 2.0 over a byte stream, one message per line (ACP transport, FR-15, NFR-6).

``JsonRpcConnection(reader, writer)`` works on an ``asyncio.StreamReader`` (e.g. the stdout of
an agent process) and anything with ``write(bytes)`` and ``async drain()`` (e.g. its stdin):

- ``request()`` sends a request with a fresh integer ``id`` and waits for the matching
  response; responses may arrive in any order. An error response raises ``JsonRpcError``
  with its ``code``; end of stream raises ``ConnectionClosed`` in every waiting caller.
- ``notify()`` sends a notification.
- incoming requests go to ``request_handler(method, params)``; its return value is sent as the
  result, a raised ``JsonRpcError`` as the error. Each request runs in its own task, so a
  handler may wait (e.g. for the user to grant a permission) without blocking the stream.
- incoming notifications go to ``notification_handler(method, params)``. They are handled in
  the reader loop, in arrival order and before any later response is delivered, so the
  handler must be quick (it may be a coroutine; it is awaited before the next line is read).
- lines that are not JSON objects are skipped (DEBUG log); a line longer than ``max_line``
  (16 MiB) closes the connection, because the message it carried cannot be recovered.
- all traffic is logged at DEBUG with the values of ``env`` and ``headers`` keys replaced by
  ``[redacted]`` (they carry secrets of agents and MCP servers).
"""

import asyncio
import contextlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

log = logging.getLogger(__name__)

MAX_LINE = 16 * 1024 * 1024
READ_CHUNK = 64 * 1024
LOG_TEXT_LIMIT = 4096
REDACTED = "[redacted]"
REDACTED_KEYS = frozenset({"env", "headers"})

# Standard JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

type RequestHandler = Callable[[str, Any], Awaitable[Any] | Any]
type NotificationHandler = Callable[[str, Any], Awaitable[None] | None]


class Writer(Protocol):
    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...


class JsonRpcError(Exception):
    """An error response (received, or raised by a request handler to be sent)."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"{message} ({code})")
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


class ConnectionClosed(Exception):
    """The stream ended (or broke) before the response arrived."""


def redact(value: Any) -> Any:
    """Copy of ``value`` with every ``env``/``headers`` value replaced by ``[redacted]``."""
    if isinstance(value, dict):
        return {
            key: (REDACTED if isinstance(key, str) and key.lower() in REDACTED_KEYS else redact(v))
            for key, v in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _log_text(message: Any) -> str:
    """Redacted, shortened JSON of ``message`` for the DEBUG log. Never raises.

    ``json.loads`` accepts far deeper nesting than ``redact`` (plain recursion) can walk, so
    building the log text must not be able to break the connection.
    """
    try:
        return _shorten(json.dumps(redact(message), ensure_ascii=False))
    except RecursionError:
        return "<message too deeply nested to log>"
    except (TypeError, ValueError):
        return "<message not encodable as JSON>"


def _shorten(text: str, limit: int = LOG_TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… ({len(text)} chars)"


class JsonRpcConnection:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: Writer,
        *,
        request_handler: RequestHandler | None = None,
        notification_handler: NotificationHandler | None = None,
        name: str = "jsonrpc",
        max_line: int = MAX_LINE,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._request_handler = request_handler
        self._notification_handler = notification_handler
        self.name = name
        self._max_line = max_line
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._result_hooks: dict[int, Callable[[Any], None]] = {}
        self._handler_tasks: set[asyncio.Task[None]] = set()
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = asyncio.Event()
        self.close_reason: str | None = None

    # -- lifecycle -------------------------------------------------------------------------

    def start(self) -> None:
        """Start reading. Call once, from a running event loop."""
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._read_loop(), name=f"{self.name}-reader")

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        """Stop reading and fail pending requests. Does not close the writer."""
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        self._shutdown("closed")

    def _shutdown(self, reason: str) -> None:
        if self._closed.is_set():
            return
        self.close_reason = reason
        self._closed.set()
        log.debug("%s: connection closed: %s", self.name, reason)
        pending, self._pending = self._pending, {}
        self._result_hooks.clear()
        for future in pending.values():
            if not future.done():
                future.set_exception(ConnectionClosed(reason))
        for task in list(self._handler_tasks):
            task.cancel()

    # -- sending ---------------------------------------------------------------------------

    async def request(
        self,
        method: str,
        params: Any = None,
        *,
        timeout: float | None = None,
        on_result: Callable[[Any], None] | None = None,
    ) -> Any:
        """Send a request and return its ``result``.

        Raises ``JsonRpcError`` for an error response, ``ConnectionClosed`` when the stream
        ends first and ``TimeoutError`` after ``timeout`` seconds.

        ``on_result`` is called with a successful ``result`` by the reader itself, before
        the next incoming line is handled (the awaiting caller resumes only later). It lets
        the caller register state that notifications right after the response refer to.
        """
        if self.closed:
            raise ConnectionClosed(self.close_reason or "closed")
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        if on_result is not None:
            self._result_hooks[request_id] = on_result
        try:
            await self._send(message)
            async with asyncio.timeout(timeout):
                return await future
        finally:
            self._pending.pop(request_id, None)
            self._result_hooks.pop(request_id, None)

    async def notify(self, method: str, params: Any = None) -> None:
        if self.closed:
            raise ConnectionClosed(self.close_reason or "closed")
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    @staticmethod
    def _encode(message: dict[str, Any]) -> str:
        # allow_nan=False: NaN/Infinity are not JSON; such a reply gets the -32603 fallback.
        return json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    async def _send(self, message: dict[str, Any]) -> None:
        await self._write(self._encode(message), message)

    async def _write(self, data: str, message: dict[str, Any]) -> None:
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%s → %s", self.name, _log_text(message))
        async with self._write_lock:
            try:
                self._writer.write(data.encode() + b"\n")
                await self._writer.drain()
            except (ConnectionError, RuntimeError, OSError) as exc:
                # RuntimeError: writing to a closed transport.
                self._shutdown(f"write failed: {exc}")
                raise ConnectionClosed(self.close_reason) from exc

    # -- receiving -------------------------------------------------------------------------

    async def _read_loop(self) -> None:
        reason = "end of stream"
        try:
            async for line in self._lines():
                await self._dispatch_line(line)
        except _LineTooLong:
            reason = f"line longer than {self._max_line} bytes"
            log.warning("%s: %s, closing the connection", self.name, reason)
        except (ConnectionError, OSError) as exc:
            reason = f"read failed: {exc}"
        except asyncio.CancelledError:
            reason = "closed"
            raise
        finally:
            self._shutdown(reason)

    async def _lines(self):
        buffer = bytearray()
        while True:
            chunk = await self._reader.read(READ_CHUNK)
            if not chunk:
                if buffer:
                    yield bytes(buffer)
                return
            start = 0
            search_from = len(buffer)
            buffer += chunk
            while True:
                end = buffer.find(b"\n", search_from)
                if end < 0:
                    break
                if end - start > self._max_line:
                    raise _LineTooLong
                yield bytes(buffer[start:end])
                start = search_from = end + 1
            del buffer[:start]
            if len(buffer) > self._max_line:
                raise _LineTooLong

    async def _dispatch_line(self, line: bytes) -> None:
        line = line.rstrip(b"\r")
        if not line.strip():
            return
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            # RecursionError: absurdly deep nesting; skip the line like any other bad one.
            log.debug(
                "%s: ignoring non-JSON line: %s",
                self.name,
                _shorten(line.decode(errors="replace"), 200),
            )
            return
        if not isinstance(message, dict):
            log.debug(
                "%s: ignoring non-object message: %s", self.name, _shorten(repr(message), 200)
            )
            return
        if log.isEnabledFor(logging.DEBUG):
            log.debug("%s ← %s", self.name, _log_text(message))

        method = message.get("method")
        if isinstance(method, str):
            if "id" in message:
                self._start_request_handler(message["id"], method, message.get("params"))
            else:
                await self._handle_notification(method, message.get("params"))
        elif "id" in message and ("result" in message or "error" in message):
            self._handle_response(message)
        else:
            log.debug("%s: ignoring message that is neither request nor response", self.name)

    def _handle_response(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        # bool is an int subclass: "id": true must not match request 1.
        is_int_id = isinstance(request_id, int) and not isinstance(request_id, bool)
        future = self._pending.get(request_id) if is_int_id else None
        if future is None or future.done():
            log.debug("%s: response for unknown id %r", self.name, request_id)
            return
        error = message.get("error")
        if "error" in message and error is not None:
            if isinstance(error, dict):
                code = error.get("code")
                future.set_exception(
                    JsonRpcError(
                        code if isinstance(code, int) else INTERNAL_ERROR,
                        str(error.get("message", "")),
                        error.get("data"),
                    )
                )
            else:
                future.set_exception(JsonRpcError(INTERNAL_ERROR, str(error)))
        else:
            result = message.get("result")
            hook = self._result_hooks.pop(request_id, None)
            if hook is not None:
                try:
                    hook(result)
                except Exception:
                    log.exception("%s: result hook of request %r failed", self.name, request_id)
            future.set_result(result)

    async def _handle_notification(self, method: str, params: Any) -> None:
        if self._notification_handler is None:
            return
        try:
            result = self._notification_handler(method, params)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("%s: notification handler failed for %s", self.name, method)

    def _start_request_handler(self, request_id: Any, method: str, params: Any) -> None:
        task = asyncio.create_task(
            self._handle_request(request_id, method, params), name=f"{self.name}-{method}"
        )
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_tasks.discard)

    async def _handle_request(self, request_id: Any, method: str, params: Any) -> None:
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        try:
            if self._request_handler is None:
                raise JsonRpcError(METHOD_NOT_FOUND, f"Method not found: {method}")
            result = self._request_handler(method, params)
            if inspect.isawaitable(result):
                result = await result
            response["result"] = result
        except JsonRpcError as exc:
            response["error"] = exc.to_dict()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s: request handler failed for %s", self.name, method)
            response["error"] = {"code": INTERNAL_ERROR, "message": "Internal error"}
        try:
            data = self._encode(response)
        except (TypeError, ValueError, RecursionError):
            # The handler returned (or the error carried) something JSON cannot encode.
            # The agent still needs an answer, otherwise it waits forever.
            log.exception("%s: cannot encode the reply to %s", self.name, method)
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": INTERNAL_ERROR, "message": "Internal error"},
            }
            data = self._encode(response)
        if self.closed:
            return
        with contextlib.suppress(ConnectionClosed):
            await self._write(data, response)


class _LineTooLong(Exception):
    pass
