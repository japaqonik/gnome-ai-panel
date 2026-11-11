"""Edge cases of JsonRpcConnection added by the tester (S2-T3)."""

import asyncio
import json
import logging

import pytest

from app.backends.jsonrpc import (
    INTERNAL_ERROR,
    ConnectionClosed,
    JsonRpcError,
)
from tests.unit.test_jsonrpc import Peer, log_text, make_conn


@pytest.fixture
async def peer() -> Peer:
    return Peer()


@pytest.fixture
def debug_records():
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


async def test_line_exactly_at_limit_passes_and_one_byte_more_closes() -> None:
    limit = 1000
    ok = Peer()
    conn = make_conn(ok, max_line=limit)
    task = asyncio.create_task(conn.request("m"))
    msg = await ok.read()
    head = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": ""}).encode()
    body = head[:-2] + b"x" * (limit - len(head)) + b'"}'
    assert len(body) == limit
    ok.send_raw(body + b"\n")
    assert len(await asyncio.wait_for(task, 2)) == limit - len(head)
    await conn.close()

    too_long = Peer()
    conn2 = make_conn(too_long, max_line=limit)
    task2 = asyncio.create_task(conn2.request("m"))
    msg2 = await too_long.read()
    head2 = json.dumps({"jsonrpc": "2.0", "id": msg2["id"], "result": ""}).encode()
    body2 = head2[:-2] + b"x" * (limit + 1 - len(head2)) + b'"}'
    too_long.send_raw(body2 + b"\n")
    with pytest.raises(ConnectionClosed, match="longer than"):
        await asyncio.wait_for(task2, 2)


async def test_invalid_utf8_and_non_object_lines_are_skipped(peer: Peer, debug_records) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(b"\xff\xfe\xfd not utf8\n")
    peer.send_raw(b"[1, 2, 3]\n")
    peer.send_raw(b'"just a string"\n')
    peer.send_raw(b"42\n")
    peer.send_raw(b"\n   \n")
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"})
    assert await asyncio.wait_for(task, 2) == "ok"
    assert not conn.closed
    assert "non-JSON" in log_text(debug_records)
    await conn.close()


async def test_response_for_unknown_id_is_ignored(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": 9999, "result": "stray"})
    peer.send({"jsonrpc": "2.0", "id": str(msg["id"]), "result": "string id"})
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
    assert await asyncio.wait_for(task, 2) is None
    await conn.close()


async def test_error_null_with_result_is_success(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"a": 1}, "error": None})
    assert await asyncio.wait_for(task, 2) == {"a": 1}
    await conn.close()


async def test_error_with_non_int_code_maps_to_internal_error(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": "x", "message": "bad"}})
    with pytest.raises(JsonRpcError) as info:
        await asyncio.wait_for(task, 2)
    assert info.value.code == INTERNAL_ERROR
    assert info.value.message == "bad"
    await conn.close()


async def test_request_and_notify_after_eof_raise_connection_closed(peer: Peer) -> None:
    conn = make_conn(peer)
    peer.eof()
    await asyncio.wait_for(conn.wait_closed(), 2)
    assert conn.close_reason == "end of stream"
    with pytest.raises(ConnectionClosed):
        await conn.request("m")
    with pytest.raises(ConnectionClosed):
        await conn.notify("n")


async def test_eof_after_partial_line_still_fails_pending(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": 1}).encode()[:-3])
    peer.eof()
    with pytest.raises(ConnectionClosed):
        await asyncio.wait_for(task, 2)


async def test_last_line_without_newline_is_delivered_before_eof(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": 7}).encode())
    peer.eof()
    assert await asyncio.wait_for(task, 2) == 7


async def test_many_concurrent_requests_resolve_in_reverse_order(peer: Peer) -> None:
    conn = make_conn(peer)
    tasks = [asyncio.create_task(conn.request("m", {"n": i})) for i in range(50)]
    msgs = [await peer.read() for _ in range(50)]
    assert len({m["id"] for m in msgs}) == 50
    for m in reversed(msgs):
        peer.send({"jsonrpc": "2.0", "id": m["id"], "result": m["params"]["n"] * 2})
    results = await asyncio.wait_for(asyncio.gather(*tasks), 2)
    assert results == [i * 2 for i in range(50)]
    await conn.close()


async def test_concurrent_large_writes_are_not_interleaved(peer: Peer) -> None:
    conn = make_conn(peer)
    big = "y" * 30_000  # under the 64 KiB readline limit of the test peer
    await asyncio.gather(*(conn.notify("n", {"i": i, "data": big}) for i in range(5)))
    seen = set()
    for _ in range(5):
        msg = await peer.read()
        assert msg["params"]["data"] == big
        seen.add(msg["params"]["i"])
    assert seen == set(range(5))
    await conn.close()


async def test_incoming_request_params_with_env_are_redacted_in_log(
    peer: Peer, debug_records
) -> None:
    reply_value = {"headers": {"Authorization": "Bearer zz9"}}
    conn = make_conn(peer, request_handler=lambda m, p: reply_value)
    peer.send(
        {"jsonrpc": "2.0", "id": "r1", "method": "x", "params": {"ENV": {"K": "topsecret-in"}}}
    )
    reply = await peer.read()
    # The wire keeps the real value.
    assert reply["result"]["headers"]["Authorization"] == "Bearer zz9"
    text = log_text(debug_records)
    assert "topsecret-in" not in text
    assert "zz9" not in text
    await conn.close()


async def test_unserialisable_handler_result_still_gets_an_error_reply(peer: Peer) -> None:
    """A handler bug must not leave the agent waiting for a reply forever."""
    conn = make_conn(peer, request_handler=lambda m, p: {"bad": object()})
    peer.send({"jsonrpc": "2.0", "id": 5, "method": "x"})
    reply = await peer.read()
    assert reply["id"] == 5
    assert reply["error"]["code"] == INTERNAL_ERROR
    assert not conn.closed
    await conn.close()


async def test_handler_running_at_close_sends_nothing(peer: Peer) -> None:
    started = asyncio.Event()

    async def handler(method, params):
        started.set()
        await asyncio.sleep(10)

    conn = make_conn(peer, request_handler=handler)
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "slow"})
    await asyncio.wait_for(started.wait(), 2)
    await conn.close()
    await asyncio.sleep(0.05)
    assert peer.from_conn.reader._buffer == b""


async def test_closed_connection_ignores_late_lines(peer: Peer) -> None:
    received = []
    conn = make_conn(peer, notification_handler=lambda m, p: received.append(m))
    await conn.close()
    peer.send({"jsonrpc": "2.0", "method": "late"})
    await asyncio.sleep(0.05)
    assert received == []


async def test_deeply_nested_line_is_skipped_not_fatal(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(b"[" * 100_000 + b"]" * 100_000 + b"\n")
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"})
    assert await asyncio.wait_for(task, 2) == "ok"
    await conn.close()
