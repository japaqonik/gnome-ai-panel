"""More edge cases of JsonRpcConnection added by the tester (S2-T3 attempt 2)."""

import asyncio
import json
import sys

import pytest

from app.backends.jsonrpc import INTERNAL_ERROR, JsonRpcError
from tests.unit.test_jsonrpc import Peer, make_conn
from tests.unit.test_jsonrpc_edge import debug_records  # noqa: F401  (fixture)


@pytest.fixture
async def peer() -> Peer:
    return Peer()


def _nested(depth: int) -> dict:
    value: object = "leaf"
    for _ in range(depth):
        value = {"k": value}
    return value  # type: ignore[return-value]


async def test_unencodable_error_data_still_gets_an_error_reply(peer: Peer) -> None:
    def handler(method, params):
        raise JsonRpcError(-32001, "boom", data={"x": object()})

    conn = make_conn(peer, request_handler=handler)
    peer.send({"jsonrpc": "2.0", "id": "abc", "method": "x"})
    reply = await asyncio.wait_for(peer.read(), 2)
    assert reply["id"] == "abc"
    assert reply["error"]["code"] == INTERNAL_ERROR
    assert "result" not in reply
    await conn.close()


async def test_unencodable_reply_does_not_break_later_requests(peer: Peer) -> None:
    calls = []

    def handler(method, params):
        calls.append(method)
        return {"bad": object()} if method == "bad" else {"ok": True}

    conn = make_conn(peer, request_handler=handler)
    peer.send({"jsonrpc": "2.0", "id": 1, "method": "bad"})
    first = await asyncio.wait_for(peer.read(), 2)
    peer.send({"jsonrpc": "2.0", "id": 2, "method": "good"})
    second = await asyncio.wait_for(peer.read(), 2)
    assert first["error"]["code"] == INTERNAL_ERROR
    assert second == {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}
    assert not conn.closed
    await conn.close()


async def test_unencodable_reply_with_debug_logging(peer: Peer, debug_records) -> None:  # noqa: F811
    conn = make_conn(peer, request_handler=lambda m, p: {"bad": {1, 2}})
    peer.send({"jsonrpc": "2.0", "id": 9, "method": "x"})
    reply = await asyncio.wait_for(peer.read(), 2)
    assert reply["error"]["code"] == INTERNAL_ERROR
    await conn.close()


async def test_boolean_false_id_does_not_match_request_0(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    assert msg["id"] == 0
    peer.send({"jsonrpc": "2.0", "id": False, "result": "wrong"})
    peer.send({"jsonrpc": "2.0", "id": 0, "result": "right"})
    assert await asyncio.wait_for(task, 2) == "right"
    await conn.close()


async def test_float_id_equal_to_int_is_not_a_crash(peer: Peer) -> None:
    conn = make_conn(peer)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    peer.send({"jsonrpc": "2.0", "id": float(msg["id"]), "result": "float"})
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "int"})
    assert await asyncio.wait_for(task, 2) in {"float", "int"}
    assert not conn.closed
    await conn.close()


@pytest.mark.parametrize("depth", [200, 800])
async def test_nested_but_parseable_line_with_debug_logging(
    peer: Peer,
    debug_records,  # noqa: F811
    depth: int,
) -> None:
    """A line json.loads accepts must not kill the reader in the DEBUG log path (redact)."""
    assert depth < sys.getrecursionlimit()
    received = []
    conn = make_conn(peer, notification_handler=lambda m, p: received.append(m))
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    line = json.dumps({"jsonrpc": "2.0", "method": "deep", "params": _nested(depth)})
    peer.send_raw(line.encode() + b"\n")
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"})
    assert await asyncio.wait_for(task, 2) == "ok"
    assert not conn.closed
    await conn.close()


async def test_deeply_nested_request_params_get_a_reply_or_are_skipped(peer: Peer) -> None:
    """Near the parser's limit: the connection must survive either way."""
    conn = make_conn(peer, request_handler=lambda m, p: "pong")
    deep = b'{"jsonrpc":"2.0","id":1,"method":"m","params":' + b"[" * 5000 + b"]" * 5000 + b"}\n"
    peer.send_raw(deep)
    peer.send({"jsonrpc": "2.0", "id": 2, "method": "m"})
    reply = await asyncio.wait_for(peer.read(), 2)
    if reply["id"] == 1:
        reply = await asyncio.wait_for(peer.read(), 2)
    assert reply == {"jsonrpc": "2.0", "id": 2, "result": "pong"}
    assert not conn.closed
    await conn.close()


@pytest.mark.parametrize("kind", ["notification", "response"])
async def test_very_deep_parseable_line_with_debug_logging_is_not_fatal(
    peer: Peer,
    debug_records,  # noqa: F811
    kind: str,
) -> None:
    """On Python 3.14 json.loads accepts depth 5000, but redact() recursion does not.

    With DEBUG logging the line is logged via redact(); that must not end the connection.
    """
    conn = make_conn(peer, notification_handler=lambda m, p: None)
    task = asyncio.create_task(conn.request("m"))
    msg = await peer.read()
    deep = b"[" * 5000 + b"]" * 5000
    if kind == "notification":
        line = b'{"jsonrpc":"2.0","method":"deep","params":' + deep + b"}\n"
    else:
        line = b'{"jsonrpc":"2.0","id":12345,"result":' + deep + b"}\n"
    peer.send_raw(line)
    peer.send({"jsonrpc": "2.0", "id": msg["id"], "result": "ok"})
    assert await asyncio.wait_for(task, 2) == "ok"
    assert not conn.closed
    await conn.close()
