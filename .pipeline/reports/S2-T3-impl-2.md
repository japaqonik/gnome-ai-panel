# Implementation report S2-T3 attempt 2
## Changes
- app/backends/jsonrpc.py:
  - `_send` is split into `_encode` (json.dumps) and `_write` (debug log + locked write), so a
    reply can be encoded before anything is written.
  - `_handle_request` encodes the reply inside its own error handling. If `json.dumps` raises
    `TypeError`, `ValueError` or `RecursionError` (for example a handler result containing
    `object()`, or a `JsonRpcError.data` that cannot be encoded), it logs the exception and sends
    `{"code": -32603, "message": "Internal error"}` with the same id instead.
  - `_dispatch_line` catches `RecursionError` from `json.loads` along with `ValueError`, so a
    deeply nested line is skipped like any other unparsable line and the connection stays open.
  - `_handle_response` no longer accepts a `bool` id (`"id": true` used to match request 1).
- tests/unit/test_jsonrpc.py: added `test_boolean_response_id_does_not_match_an_int_request`.

## Problems from previous report
- Unencodable handler result gets no reply → encoded inside error handling, falls back to an
  `INTERNAL_ERROR` reply. `test_unserialisable_handler_result_still_gets_an_error_reply` passes.
- Deeply nested line kills the connection → `RecursionError` is caught in `_dispatch_line`.
  `test_deeply_nested_line_is_skipped_not_fatal` passes.
- Suggestion: `"id": true` matched request 1 → fixed, with a test.
- Suggestion: incoming requests with `"id": null` → not changed. JSON-RPC 2.0 only discourages
  null ids; it doesn't forbid them. Ignoring such a request would leave the agent waiting
  forever, and answering it with the same (null) id is the more useful behaviour.
- Note about the fake agent's `session/request_permission` error path → left as is. It is only
  a test fake, and S2-T4 can extend it if it needs that path.

## How to verify
- `.venv/bin/pytest -q tests/unit/test_jsonrpc.py tests/unit/test_jsonrpc_edge.py` → 45 passed.
- `printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' | .venv/bin/python tests/fakes/fake_acp_agent.py --scenario echo`
  → one JSON line with `"protocolVersion": 1`.
- `make build && make lint && make test` → all exit 0.

## Command results
- build: ok, lint: ok, test: Python 371/371, GJS 1/1, UI 3/3 (Playwright fell back to Chromium
  because WebKit is missing host libraries)

## Known limitations / deviations from plan
- None.
