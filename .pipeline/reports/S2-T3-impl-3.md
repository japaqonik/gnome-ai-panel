# Implementation report S2-T3 attempt 3
## Changes
- app/backends/jsonrpc.py: new helper `_log_text(message)` builds the redacted, shortened DEBUG
  log text and never raises. A `RecursionError` from `redact()`/`json.dumps` gives
  `<message too deeply nested to log>`; `TypeError`/`ValueError` give
  `<message not encodable as JSON>`. Both the `←` log in `_dispatch_line` and the `→` log in
  `_write` use it, so DEBUG logging no longer changes behaviour.
- app/backends/jsonrpc.py: `_encode` uses `allow_nan=False`. A handler result containing
  NaN/Infinity now goes through the existing -32603 fallback instead of sending invalid JSON.
  For `request()`/`notify()` the `ValueError` is raised to the caller (the pending entry is
  removed in `finally`).
- tests/unit/test_jsonrpc.py: 3 new tests:
  - a notification nested 5000 deep, with DEBUG logging on, is delivered, the pending request
    gets `"ok"`, the placeholder is logged and the connection stays open;
  - a handler result nested 5000 deep, with DEBUG logging on, still gets a reply (a result or
    -32603) and the next request is answered;
  - a NaN handler result gets -32603.

## Problems from previous report
- DEBUG logging + a deeply nested valid line kills the connection (`_dispatch_line`), and the
  same risk in `_write` → fixed with `_log_text`. `pytest tests/unit/test_jsonrpc_edge2.py -k very_deep`
  passes (2/2), and the whole `test_jsonrpc_edge2.py` passes (10/10).
- Suggestion: NaN sent as invalid JSON → fixed with `allow_nan=False`, test added.
- Attempt 1 problems stay fixed (`test_jsonrpc_edge.py` 15/15).

## How to verify
- `.venv/bin/pytest tests/unit/test_jsonrpc.py tests/unit/test_jsonrpc_edge.py tests/unit/test_jsonrpc_edge2.py` → 58 passed
- `make build && make lint && make test` → all exit 0

## Command results
- build: ok, lint: ok, test: Python 384/384, GJS 1/1, UI 3/3 (Chromium fallback, Playwright WebKit libs missing)

## Known limitations / deviations from plan
- I kept `redact()` recursive and did not make it iterative. With very deep messages the log
  shows a placeholder instead of the content, which is enough for a debug log.
