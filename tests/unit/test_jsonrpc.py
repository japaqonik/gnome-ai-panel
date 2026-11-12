"""JsonRpcConnection on in-memory pipes (S2-T3)."""

import asyncio
import json
import logging

import pytest

from app.backends.jsonrpc import (
    INTERNAL_ERROR,
    MAX_LINE,
    METHOD_NOT_FOUND,
    ConnectionClosed,
    JsonRpcConnection,
    JsonRpcError,
    redact,
)


class MemoryWriter:
    """Writer side of an in-memory pipe: everything written appears in ``reader``."""

    def __init__(self) -> None:
        self.reader = asyncio.StreamReader()
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ConnectionResetError("pipe closed")
        self.reader.feed_data(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self.closed = True
        self.reader.feed_eof()


class Peer:
    """The other end of a connection, driven by the test line by line."""

    def __init__(self) -> None:
        self.to_conn = MemoryWriter()  # what the connection reads
        self.from_conn = MemoryWriter()  # what the connection writes

    async def read(self) -> dict:
        line = await asyncio.wait_for(self.from_conn.reader.readline(), 2)
        assert line.endswith(b"\n")
        return json.loads(line)

    def send_raw(self, data: bytes) -> None:
        self.to_conn.write(data)

    def send(self, message: dict) -> None:
        self.send_raw(json.dumps(message).encode() + b"\n")

    def eof(self) -> None:
        self.to_conn.close()


@pytest.fixture
async def peer() -> Peer:
    return Peer()


def make_conn(peer: Peer, **kwargs) -> JsonRpcConnection:
    conn = JsonRpcConnection(peer.to_conn.reader, peer.from_conn, name="test", **kwargs)
    conn.start()
    return conn


@pytest.fixture
def debug_records():
    """Records of ``app.backends.jsonrpc`` at DEBUG, independent of ``setup_logging``."""
    records: list[logging.LogRecord] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("app.backends.jsonrpc")
    handler = ListHandler(logging.DEBUG)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


def log_text(records: list[logging.LogRecord]) -> str:
    return "\n".join(r.getMessage() for r in records)


async def test_request_sends_jsonrpc_line_with_increasing_ids(peer: Peer) -> None:
    conn = make_conn(peer)
    first = asyncio.create_task(conn.request("initialize", {"protocolVersion": 1}))
    msg = await peer.read()
    assert msg == {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {"protocolVersion": 1},
    }
    second = asyncio.create_task(conn.request("ping"))
    msg2 = await peer.read()
    assert msg2 == {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    peer.send({"jsonrpc": "2.0", "id": 0, "result": {"ok": 1}})
    peer.send({"jsonrpc": "2.0", "id": 1, "result": None})
    assert await first == {"ok": 1}
    assert await second is None
    await conn.close()


async def test_responses_out_of_order_are_correlated_by_id(peer: Peer) -> None:
    conn = make_conn(peer)
    tasks = [asyncio.create_task(conn.request("m", {"n": n})) for n in range(3)]
    ids = [(await peer.read())["id"] for _ in range(3)]
    for request_id in reversed(ids):
        peer.send({"jsonrpc": "2.0", "id": request_id, "result": f"r{request_id}"})
    results = await asyncio.gather(*tasks)
    assert results == [f"r{i}" for i in ids]
    await conn.close()


async def test_error_response_raises_with_code_message_and_data(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("session/new", {}))
    msg = await peer.read()
    peer.send(
        {
            "jsonrpc": "2.0",
            "id": msg["id"],
            "error": {"code": -32000, "message": "Authentication required", "data": {"x": 1}},
        }
    )
    with pytest.raises(JsonRpcError) as info:
        await task
    assert info.value.code == -32000
    assert info.value.message == "Authentication required"
    assert info.value.data == {"x": 1}
    await conn.close()


async def test_malformed_error_object_still_raises(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "error": "bad"})
    with pytest.raises(JsonRpcError) as info:
        await task
    assert info.value.code == INTERNAL_ERROR
    await conn.close()


async def test_incoming_request_gets_handler_result(peer: Peer) -> None:
    calls = []

    async def handler(method, params):
        calls.append((method, params))
        await asyncio.sleep(0)
        return {"outcome": {"outcome": "selected", "optionId": "allow"}}

    conn = make_conn(peer, request_handler=handler)
    peer.send(
        {"jsonrpc": "2.0", "id": 7, "method": "session/request_permission", "params": {"a": 1}}
    )
    response = await peer.read()
    assert response == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"outcome": {"outcome": "selected", "optionId": "allow"}},
    }
    assert calls == [("session/request_permission", {"a": 1})]
    await conn.close()


async def test_incoming_request_with_string_id_and_sync_handler(peer: Peer) -> None:
    conn = make_conn(peer, request_handler=lambda method, params: method.upper())
    peer.send({"jsonrpc": "2.0", "id": "abc", "method": "fs/x"})
    assert await peer.read() == {"jsonrpc": "2.0", "id": "abc", "result": "FS/X"}
    await conn.close()


async def test_handler_jsonrpc_error_becomes_error_response(peer: Peer) -> None:
    def handler(method, params):
        raise JsonRpcError(-32602, "Invalid params", {"field": "x"})

    conn = make_conn(peer, request_handler=handler)
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "m"})
    response = await peer.read()
    assert response["error"] == {
        "code": -32602,
        "message": "Invalid params",
        "data": {"field": "x"},
    }
    assert "result" not in response
    await conn.close()


async def test_handler_crash_becomes_internal_error(peer: Peer) -> None:
    def handler(method, params):
        raise ValueError("secret detail")

    conn = make_conn(peer, request_handler=handler)
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "m"})
    response = await peer.read()
    assert response["error"]["code"] == INTERNAL_ERROR
    assert "secret detail" not in json.dumps(response)
    await conn.close()


async def test_no_request_handler_answers_method_not_found(peer: Peer) -> None:
    conn = make_conn(peer)
    peer.send({"jsonrpc": "2.0", "id": 3, "method": "terminal/create"})
    response = await peer.read()
    assert response["id"] == 3
    assert response["error"]["code"] == METHOD_NOT_FOUND
    await conn.close()


async def test_slow_request_handler_does_not_block_other_messages(peer: Peer) -> None:
    release = asyncio.Event()

    async def handler(method, params):
        await release.wait()
        return "late"

    notes = []
    conn = make_conn(
        peer, request_handler=handler, notification_handler=lambda m, p: notes.append(p)
    )
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "wait"})
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "method": "n", "params": 1})
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "early"})
    assert await asyncio.wait_for(task, 2) == "early"
    assert notes == [1]
    release.set()
    assert (await peer.read())["result"] == "late"
    await conn.close()


async def test_notifications_arrive_in_order_before_later_response(peer: Peer) -> None:
    seen: list = []

    async def on_note(method, params):
        await asyncio.sleep(0)
        seen.append((method, params["n"]))

    conn = make_conn(peer, notification_handler=on_note)
    task = asyncio.create_task(conn.request("session/prompt"))
    msg = await peer.read()
    for n in range(5):
        peer.send({"jsonrpc": "2.0", "method": "session/update", "params": {"n": n}})
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"stopReason": "end_turn"}})
    await task
    assert seen == [("session/update", n) for n in range(5)]
    await conn.close()


async def test_notification_handler_error_is_logged_not_fatal(peer: Peer, debug_records) -> None:
    def on_note(method, params):
        raise RuntimeError("bug")

    conn = make_conn(peer, notification_handler=on_note)
    peer.send({"jsonrpc": "2.0", "method": "x"})
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": 1})
    assert await task == 1
    assert any(r.levelno == logging.ERROR for r in debug_records)
    await conn.close()


async def test_notify_sends_message_without_id(peer: Peer) -> None:
    conn = make_conn(peer)
    await conn.notify("session/cancel", {"sessionId": "s1"})
    assert await peer.read() == {
        "jsonrpc": "2.0",
        "method": "session/cancel",
        "params": {"sessionId": "s1"},
    }
    await conn.close()


async def test_garbage_lines_are_skipped_and_logged_at_debug(peer: Peer, debug_records) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(b"garbage\n\n   \n[1, 2]\n\xff\xfe not utf8\n42\n")
    peer.send({"jsonrpc": "2.0", "result": "no id"})
    peer.send({"jsonrpc": "2.0", "id": 999, "result": "unknown id"})
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"})
    assert await task == "ok"
    assert not conn.closed
    text = log_text(debug_records)
    assert "ignoring non-JSON line: garbage" in text
    assert all(r.levelno == logging.DEBUG for r in debug_records)
    await conn.close()


async def test_crlf_line_endings_are_accepted(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": 5}).encode() + b"\r\n")
    assert await task == 5
    await conn.close()


async def test_message_split_across_many_writes(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    data = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": "ż" * 10}).encode() + b"\n"
    for i in range(len(data)):
        peer.send_raw(data[i : i + 1])
        await asyncio.sleep(0)
    assert await task == "ż" * 10
    await conn.close()


async def test_one_mib_line_passes(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    big = "x" * (1024 * 1024)
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": big})
    assert await asyncio.wait_for(task, 5) == big
    await conn.close()


def test_default_line_limit_is_16_mib() -> None:
    assert MAX_LINE == 16 * 1024 * 1024


async def test_line_over_limit_closes_connection(peer: Peer) -> None:
    conn = make_conn(peer, max_line=1024)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "y" * 2048})
    with pytest.raises(ConnectionClosed, match="longer than 1024"):
        await asyncio.wait_for(task, 2)
    assert conn.closed


async def test_line_over_limit_without_newline_closes_connection(peer: Peer) -> None:
    conn = make_conn(peer, max_line=1024)
    task = asyncio.create_task(conn.request("m"))
    await peer.read()
    peer.send_raw(b"z" * 5000)
    with pytest.raises(ConnectionClosed):
        await asyncio.wait_for(task, 2)


async def test_eof_fails_all_pending_requests(peer: Peer) -> None:
    conn = make_conn(peer)
    tasks = [asyncio.create_task(conn.request("m")) for _ in range(3)]
    for _ in range(3):
        await peer.read()
    peer.eof()
    for task in tasks:
        with pytest.raises(ConnectionClosed, match="end of stream"):
            await asyncio.wait_for(task, 2)
    await asyncio.wait_for(conn.wait_closed(), 2)
    assert conn.closed
    with pytest.raises(ConnectionClosed):
        await conn.request("again")
    with pytest.raises(ConnectionClosed):
        await conn.notify("again")


async def test_eof_cancels_running_request_handlers(peer: Peer) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(method, params):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    conn = make_conn(peer, request_handler=handler)
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "wait"})
    await asyncio.wait_for(started.wait(), 2)
    peer.eof()
    await asyncio.wait_for(cancelled.wait(), 2)
    assert conn.closed


async def test_close_fails_pending_requests(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    await peer.read()
    await conn.close()
    with pytest.raises(ConnectionClosed, match="closed"):
        await task
    assert conn.close_reason == "closed"
    await conn.close()  # idempotent


async def test_broken_writer_raises_connection_closed(peer: Peer) -> None:
    conn = make_conn(peer)
    peer.from_conn.closed = True
    with pytest.raises(ConnectionClosed, match="write failed"):
        await conn.request("m")
    assert conn.closed


async def test_request_timeout_removes_pending(peer: Peer) -> None:
    conn = make_conn(peer)
    with pytest.raises(TimeoutError):
        await conn.request("m", timeout=0.05)
    msg = await peer.read()
    # A late response is ignored.
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": 1})
    task = asyncio.create_task(conn.request("n"))
    msg2 = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg2["id"], "result": 2})
    assert await task == 2
    await conn.close()


async def test_two_connections_talk_to_each_other() -> None:
    a_to_b = MemoryWriter()
    b_to_a = MemoryWriter()

    async def server_handler(method, params):
        # The server calls back into the client while handling the request.
        answer = await server.request("client/ask", {"q": params["q"]})
        return {"echo": params["q"], "client_said": answer}

    client = JsonRpcConnection(
        b_to_a.reader, a_to_b, request_handler=lambda m, p: f"ok:{p['q']}", name="client"
    )
    server = JsonRpcConnection(a_to_b.reader, b_to_a, request_handler=server_handler, name="srv")
    client.start()
    server.start()
    result = await asyncio.wait_for(client.request("ask", {"q": "hi"}), 2)
    assert result == {"echo": "hi", "client_said": "ok:hi"}
    a_to_b.close()
    await asyncio.wait_for(server.wait_closed(), 2)
    await client.close()


def test_redact_replaces_env_and_headers_recursively() -> None:
    message = {
        "params": {
            "cwd": "/work/dir",
            "mcpServers": [
                {"name": "a", "env": [{"name": "TOKEN", "value": "s3cr3t"}], "args": ["x"]},
                {"name": "b", "headers": [{"name": "Authorization", "value": "Bearer s3cr3t"}]},
            ],
            "Env": {"K": "s3cr3t"},
        }
    }
    redacted = redact(message)
    assert "s3cr3t" not in json.dumps(redacted)
    assert redacted["params"]["mcpServers"][0]["env"] == "[redacted]"
    assert redacted["params"]["mcpServers"][0]["args"] == ["x"]
    assert redacted["params"]["mcpServers"][1]["headers"] == "[redacted]"
    assert redacted["params"]["Env"] == "[redacted]"
    assert redacted["params"]["cwd"] == "/work/dir"
    # The original is untouched.
    assert message["params"]["mcpServers"][0]["env"][0]["value"] == "s3cr3t"


async def test_traffic_log_redacts_env_and_headers(peer: Peer, debug_records) -> None:
    conn = make_conn(peer)
    params = {
        "cwd": "/work",
        "mcpServers": [
            {
                "name": "gh",
                "command": "srv",
                "env": [{"name": "GITHUB_TOKEN", "value": "supersecret-env"}],
                "headers": [{"name": "x-api-key", "value": "supersecret-hdr"}],
            }
        ],
    }
    task = asyncio.create_task(conn.request("session/new", params))
    msg = await peer.read()
    # The wire carries the real values; only the log is redacted.
    assert msg["params"]["mcpServers"][0]["env"][0]["value"] == "supersecret-env"
    peer.send(
        {"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": "s", "env": {"A": "inbound"}}}
    )
    await task
    text = log_text(debug_records)
    assert "session/new" in text
    assert "/work" in text
    assert "[redacted]" in text
    assert "supersecret-env" not in text
    assert "supersecret-hdr" not in text
    assert "inbound" not in text
    await conn.close()


async def test_no_traffic_logged_above_debug(peer: Peer, debug_records) -> None:
    logging.getLogger("app.backends.jsonrpc").setLevel(logging.INFO)
    conn = make_conn(peer)
    await conn.notify("x", {"v": 1})
    await peer.read()
    assert debug_records == []
    await conn.close()


async def test_boolean_response_id_does_not_match_an_int_request() -> None:
    peer = Peer()
    conn = make_conn(peer)
    first = asyncio.create_task(conn.request("a"))
    second = asyncio.create_task(conn.request("b"))
    ids = [(await peer.read())["id"] for _ in range(2)]
    assert 1 in ids
    peer.send({"jsonrpc": "2.0", "id": True, "result": "bool"})
    for request_id in ids:
        peer.send({"jsonrpc": "2.0", "id": request_id, "result": request_id})
    assert await asyncio.wait_for(first, 2) == ids[0]
    assert await asyncio.wait_for(second, 2) == ids[1]
    await conn.close()


def _deep_list(depth: int) -> list:
    value: list = []
    for _ in range(depth - 1):
        value = [value]
    return value


async def test_deep_incoming_notification_with_debug_logs_a_placeholder(
    peer: Peer, debug_records
) -> None:
    """json.loads accepts depth 5000, redact() cannot walk it; the log must not raise."""
    received = []
    conn = make_conn(peer, notification_handler=lambda m, p: received.append(m))
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(
        b'{"jsonrpc":"2.0","method":"deep","params":' + b"[" * 5000 + b"]" * 5000 + b"}\n"
    )
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"})
    assert await asyncio.wait_for(task, 2) == "ok"
    assert received == ["deep"]
    assert "too deeply nested to log" in log_text(debug_records)
    assert not conn.closed
    await conn.close()


async def test_deep_handler_result_with_debug_still_gets_a_reply(peer: Peer, debug_records) -> None:
    deep = _deep_list(5000)
    conn = make_conn(peer, request_handler=lambda m, p: deep if m == "deep" else "pong")
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "deep"})
    reply = await peer.read()
    assert reply["id"] == 1
    assert "result" in reply or reply["error"]["code"] == INTERNAL_ERROR
    peer.send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert await peer.read() == {"jsonrpc": "2.0", "id": 2, "result": "pong"}
    assert not conn.closed
    await conn.close()


async def test_nan_handler_result_gets_an_internal_error(peer: Peer) -> None:
    conn = make_conn(peer, request_handler=lambda m, p: {"x": float("nan")})
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "m"})
    reply = await peer.read()
    assert reply["id"] == 1
    assert reply["error"]["code"] == INTERNAL_ERROR
    await conn.close()


async def test_on_result_runs_before_the_next_line_is_handled(peer: Peer) -> None:
    # S4-T4: session/new registers the session in on_result, so a session/update sent
    # right after the answer must see it.
    order: list[str] = []
    conn = make_conn(
        peer, notification_handler=lambda method, params: order.append(f"note:{params['n']}")
    )
    task = asyncio.create_task(
        conn.request("session/new", on_result=lambda result: order.append(f"hook:{result}"))
    )
    msg = await peer.read()
    peer.send_raw(
        json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": "s1"}).encode()
        + b"\n"
        + json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {"n": 1}}).encode()
        + b"\n"
    )
    assert await task == "s1"
    await asyncio.sleep(0.05)
    assert order == ["hook:s1", "note:1"]
    await conn.close()


async def test_on_result_not_called_for_error_and_failure_still_delivers(peer: Peer) -> None:
    calls: list = []
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("x", on_result=calls.append))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -1, "message": "no"}})
    with pytest.raises(JsonRpcError):
        await task
    assert calls == []

    def broken(result) -> None:
        raise RuntimeError("hook bug")

    task = asyncio.create_task(conn.request("y", on_result=broken))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": 7})
    assert await task == 7
    await conn.close()


async def test_on_result_dropped_after_timeout_and_cancel(peer: Peer) -> None:
    # A late answer to a request that already timed out or was cancelled must not run the
    # hook (it would register a session nobody waits for).
    calls: list = []
    conn = make_conn(peer)
    with pytest.raises(TimeoutError):
        await conn.request("slow", timeout=0.05, on_result=calls.append)
    timed_out = await peer.read()

    task = asyncio.create_task(conn.request("cancelled", on_result=calls.append))
    cancelled = await peer.read()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    peer.send({"jsonrpc": "2.0", "id": timed_out["id"], "result": "late"})
    peer.send({"jsonrpc": "2.0", "id": cancelled["id"], "result": "late"})
    # The connection still works and only the live request's hook runs.
    task = asyncio.create_task(conn.request("live", on_result=calls.append))
    live = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": live["id"], "result": "ok"})
    assert await task == "ok"
    assert calls == ["ok"]
    assert conn._result_hooks == {}
    await conn.close()


async def test_on_result_not_called_when_connection_closes(peer: Peer) -> None:
    calls: list = []
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("x", on_result=calls.append))
    await peer.read()
    peer.eof()
    with pytest.raises(ConnectionClosed):
        await task
    assert calls == []
    assert conn._result_hooks == {}
    await conn.close()
