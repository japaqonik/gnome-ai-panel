# Test report S2-T3 attempt 1
Verdict: FAIL

## Command results
- build: exit 0
- lint: exit 0 (ruff check, ruff format --check, ESLint; schema check skipped, no schemas yet)
- test (before my tests were added): exit 0. test-py 355/355, test-gjs 1/1, test-ui 3/3. The UI tests ran on Chromium because Playwright WebKit lacks `libevent-2.1.so.7`.
- With my new file `tests/unit/test_jsonrpc_edge.py`, `pytest tests/unit` gives 324 passed and 2 failed. Both failures are real bugs, listed under Problems.

## Done-when criteria
- [x] `printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' | .venv/bin/python tests/fakes/fake_acp_agent.py --scenario echo` prints one JSON line with `"protocolVersion": 1` and exits 0.
- [x] `make test` exits 0 with the implementer's tests. It fails now because my added tests expose the bugs below.

## "Tests" line of the task
All required cases exist in `tests/unit/test_jsonrpc.py` and assert real behaviour: out-of-order correlation, error to `JsonRpcError` with code, incoming request answered, `garbage` skipped, 1 MiB line, EOF fails pending requests with `ConnectionClosed`, `env` redacted in the log. `tests/integration/test_fake_acp_agent.py` runs every PLAN scenario of the fake agent as a subprocess. Every scenario from PLAN "Commands" is implemented, `tool` also sends a thought, and `--record` works.

## Tests added
- `tests/unit/test_jsonrpc_edge.py` (15 tests, 13 pass):
  - a line of exactly `max_line` bytes passes; one byte more closes the connection;
  - invalid UTF-8, JSON array/string/number and blank lines are skipped;
  - responses with an unknown id or a string id are ignored; `"result": null` is returned as `None`;
  - `error: null` together with `result` counts as success; a non-int error code maps to -32603;
  - `request`/`notify` after EOF raise `ConnectionClosed`; a partial line followed by EOF fails pending requests; a last line without a newline is still delivered;
  - 50 concurrent requests answered in reverse order; concurrent large notifications are not interleaved on the wire;
  - `ENV` in incoming params and `headers` in a handler result are redacted in the log but kept on the wire;
  - a handler still running at `close()` sends nothing; lines after `close()` are not dispatched;
  - **FAIL** `test_unserialisable_handler_result_still_gets_an_error_reply`;
  - **FAIL** `test_deeply_nested_line_is_skipped_not_fatal`.

## Problems (for the implementer; each actionable)
1. **A handler result that cannot be encoded gets no reply, so the agent waits forever.**
   - Reproduce: `.venv/bin/pytest tests/unit/test_jsonrpc_edge.py::test_unserialisable_handler_result_still_gets_an_error_reply`. The handler returns `{"bad": object()}`.
   - Expected: an error reply `{"id": 5, "error": {"code": -32603, …}}`, as the report says for "any other exception".
   - Actual: `json.dumps` raises `TypeError` in `_send`, called at the end of `_handle_request`, outside its `try`. Nothing is sent, and the task ends with an unretrieved exception.
   - Where: `app/backends/jsonrpc.py`, `_handle_request`. Encode the response inside the error handling, and on failure send `INTERNAL_ERROR`.
2. **One deeply nested JSON line from the agent kills the whole connection.**
   - Reproduce: `.venv/bin/pytest tests/unit/test_jsonrpc_edge.py::test_deeply_nested_line_is_skipped_not_fatal`. The line is `[` × 100 000 followed by `]` × 100 000.
   - Expected: the line is skipped like other unparsable lines, and the pending request later gets its result.
   - Actual: `json.loads` raises `RecursionError`, which is not a `ValueError`. It escapes `_read_loop`, so every pending request fails with the misleading reason `ConnectionClosed: end of stream`, and the reader task dies with an unhandled exception.
   - Where: `app/backends/jsonrpc.py`, `_dispatch_line`. Also catch `RecursionError` there. `redact()` recurses too, but it only runs on input that `json.loads` already accepted.

## Suggestions (non-blocking)
- `_handle_response` accepts `"id": true` as id 1 (`isinstance(True, int)` is true and `True == 1`). Exclude `bool`.
- Incoming requests with `"id": null` are handled as requests and answered with `id: null`. JSON-RPC discourages null ids. Treating them as invalid would be cleaner.
- In the fake agent, an error reply to `session/request_permission` makes the prompt task die without answering `session/prompt`. That is acceptable for a test fake, but worth knowing in S2-T4.
- Exploratory runs: the `crash` scenario prints `boom` on stderr and exits 3. An unknown `--scenario` exits 2 with the argparse usage. `make run-headless` and `make stop` still work.
