# Implementation report S4-T4 attempt 2

## Changes
- `app/backends/jsonrpc.py`: `JsonRpcConnection.request()` takes an optional `on_result` callback. The reader calls it with a successful `result` before it resolves the future, so it runs before the next incoming line is handled. It is not called for error responses. An exception in the callback is logged and the result is still delivered. Callbacks are dropped together with the request (timeout, cancel) and on shutdown.
- `app/backends/acp.py`: `new_session()` registers the session in that callback (`_register_session`), so a `session/update` sent right after the `session/new` answer finds it. The session is not registered when the backend is closed or the process is stopping. If the session is gone by the time `new_session()` resumes (the process crashed in between), it raises `ACP_SESSION_LOST` (`crashed`) instead of returning a dead id. `_new_session_id()` holds the shared `sessionId` validation. `_request()` passes `on_result` through.
- `tests/unit/test_jsonrpc.py`: 2 tests. One checks that the hook runs before a notification on the next line. The other checks that there is no hook call for an error response and that a failing hook still delivers the result.

## Problems from previous report
- A `config_option_update` sent right after the `session/new` answer was lost → fixed. The session is now registered by the JSON-RPC reader, before the following line is handled (the first fix suggested in the report). `tests/integration/test_models_acp_edge.py` passed 15 runs in a row (5/5 each run).

## How to verify
- `for i in $(seq 10); do .venv/bin/pytest -q tests/integration/test_models_acp_edge.py | tail -1; done` → `5 passed` every time
- `.venv/bin/pytest -q tests/unit/test_jsonrpc.py` → 35 passed

## Command results
- build: ok
- lint: ok
- test (`PW_BROWSER=chromium make test`): test-py 844/844, test-gjs 1/1, test-ui 136/136 (Chromium; Playwright WebKit cannot launch on this machine)

## Known limitations / deviations from plan
- Same as attempt 1. README is unchanged, because the fix does not change any user-visible behaviour or instructions.
