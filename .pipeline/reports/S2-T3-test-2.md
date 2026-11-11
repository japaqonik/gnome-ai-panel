# Test report S2-T3 attempt 2
Verdict: FAIL

## Command results
- build: exit 0
- lint: exit 0 (ruff check, ruff format --check, ESLint; schema check skipped, no schemas yet)
- test (before my new file): exit 0. test-py 371/371, test-gjs 1/1, test-ui 3/3 (Chromium fallback, Playwright WebKit lacks `libevent-2.1.so.7`).
- With my new file `tests/unit/test_jsonrpc_edge2.py`: `pytest tests/unit tests/integration/test_fake_acp_agent.py` gives 358 passed, 2 failed. Both failures are the same bug (Problem 1).

## Done-when criteria
- [x] `printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' | .venv/bin/python tests/fakes/fake_acp_agent.py --scenario echo` prints one JSON line containing `"protocolVersion": 1`, rc=0.
- [x] `make test` exits 0 with the implementer's tests and my attempt-1 tests. It now fails because of the two new tests that expose Problem 1.

## Problems from attempt 1
- Unencodable handler result gets no reply: fixed. `test_unserialisable_handler_result_still_gets_an_error_reply` passes; I also checked unencodable `JsonRpcError.data`, a string id, DEBUG logging on, and that a later request is still answered.
- Deeply nested line (`[`×100 000) kills the connection: fixed for that input. `test_deeply_nested_line_is_skipped_not_fatal` passes. A related case still fails, see Problem 1.
- Suggestion `"id": true`: fixed with a test; I added `"id": false` vs request 0, which passes.
- Edge tests from attempt 1 are unchanged (15 tests) and none are skipped.

## Tests added
- `tests/unit/test_jsonrpc_edge2.py` (10 tests, 8 pass):
  - unencodable `JsonRpcError.data` with id `"abc"` gets a -32603 reply with the same id;
  - after an unencodable reply the next request is still answered and the connection stays open;
  - unencodable reply (a `set`) with DEBUG logging still gets -32603;
  - `"id": false` does not match request 0;
  - a float id equal to the request id does not crash the connection;
  - nested notifications at depth 200 and 800 with DEBUG logging pass;
  - a request with params nested 5000 deep (no DEBUG) does not break the connection;
  - **FAIL** `test_very_deep_parseable_line_with_debug_logging_is_not_fatal[notification]` and `[response]`.

## Problems (for the implementer; each actionable)
1. **With DEBUG logging, one deeply nested but valid JSON line from the agent kills the connection.**
   - Reproduce: `.venv/bin/pytest tests/unit/test_jsonrpc_edge2.py -k very_deep`. The line is a notification (or a response with an unknown id) whose params are `[`×5000 `]`×5000.
   - Cause: on Python 3.14, `json.loads` limits depth by C stack, so it accepts depth 5000 (and 50 000; it fails only at around 99 000). `redact()` is plain Python recursion and hits the recursion limit of 1000. In `_dispatch_line`, the `log.debug(... json.dumps(redact(message)) ...)` call runs outside any `try`. The `RecursionError` escapes `_read_loop`, so every pending request fails with `ConnectionClosed: end of stream` and the reader task dies with "Task exception was never retrieved".
   - Expected: the line is handled or skipped, the pending request gets `"ok"`, and the connection stays open. DEBUG must not change behaviour. `AI_PANEL_DEBUG=1` and `make run-headless` enable it.
   - Where: `app/backends/jsonrpc.py`, `_dispatch_line` (the `←` log) and `_write` (the `→` log, which runs before writing, so a deeply nested handler result would make `_handle_request` raise and send no reply). Fix suggestion: make building the log text never raise, for example a helper that catches `RecursionError` and logs a placeholder such as `<message too deeply nested to log>`. An iterative `redact` would also work.

## Suggestions (non-blocking)
- `_encode` uses the default `allow_nan=True`, so a handler result containing `float("nan")` is sent as `NaN`, which is not valid JSON for the agent. `allow_nan=False` would send it through the existing -32603 fallback.
- `"id": null` handling was kept on purpose; the reasoning in impl-2 is acceptable.
