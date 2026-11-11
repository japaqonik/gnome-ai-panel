"""Edge cases of JsonRpcConnection added by the tester (S2-T3 attempt 3)."""

import asyncio
import logging

import pytest

from app.backends.jsonrpc import JsonRpcError
from tests.unit.test_jsonrpc import Peer, make_conn

DEEP = b"[" * 5000 + b"]" * 5000


@pytest.fixture
async def peer() -> Peer:
    return Peer()


@pytest.fixture(params=[False, True], ids=["info", "debug"])
def log_level(request):
    logger = logging.getLogger("app.backends.jsonrpc")
    old = logger.level
    logger.setLevel(logging.DEBUG if request.param else logging.INFO)
    yield request.param
    logger.setLevel(old)


async def _request_survives(peer: Peer, conn, line: bytes):
    """Send ``line`` while a request is pending; the request must still be answered."""
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(line + b"\n")
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"})
    return task


async def test_deep_top_level_array_is_skipped(peer: Peer, log_level) -> None:
    """A non-object line whose repr() is deep must not break the reader."""
    received = []
    conn = make_conn(peer, notification_handler=lambda m, p: received.append(m))
    task = await _request_survives(peer, conn, DEEP)
    assert await asyncio.wait_for(task, 2) == "ok"
    assert received == []
    assert not conn.closed
    await conn.close()


async def test_deep_id_in_response_is_ignored(peer: Peer, log_level) -> None:
    conn = make_conn(peer)
    task = await _request_survives(peer, conn, b'{"jsonrpc":"2.0","id":' + DEEP + b',"result":1}')
    assert await asyncio.wait_for(task, 2) == "ok"
    assert not conn.closed
    await conn.close()


async def test_deep_id_in_request_gets_a_reply_and_later_requests_work(
    peer: Peer, log_level
) -> None:
    conn = make_conn(peer, request_handler=lambda m, p: "pong")
    peer.send_raw(b'{"jsonrpc":"2.0","id":' + DEEP + b',"method":"x"}\n')
    peer.send({"jsonrpc": "2.0", "id": 7, "method": "x"})
    replies = [await asyncio.wait_for(peer.read(), 2) for _ in range(2)]
    assert {"jsonrpc": "2.0", "id": 7, "result": "pong"} in replies
    assert not conn.closed
    await conn.close()


async def test_deep_error_message_raises_json_rpc_error(peer: Peer, log_level) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send_raw(
        b'{"jsonrpc":"2.0","id":%d,"error":{"code":-32001,"message":' % msg["id"] + DEEP + b"}}\n"
    )
    with pytest.raises(JsonRpcError) as info:
        await asyncio.wait_for(task, 2)
    assert info.value.code == -32001
    assert not conn.closed
    # the connection still serves the next request
    task2 = asyncio.create_task(conn.request("m2"))
    msg2 = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": msg2["id"], "result": "again"})
    assert await asyncio.wait_for(task2, 2) == "again"
    await conn.close()


async def test_infinity_in_own_request_params_raises_and_leaves_no_pending(peer: Peer) -> None:
    conn = make_conn(peer)
    with pytest.raises(ValueError):
        await conn.request("m", {"x": float("inf")})
    assert conn._pending == {}
    assert not conn.closed
    await conn.close()
