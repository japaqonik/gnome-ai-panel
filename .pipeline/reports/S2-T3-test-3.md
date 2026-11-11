# Test report S2-T3 attempt 3
Verdict: PASS

## Command results
- build: exit 0
- lint: exit 0 (ruff check, ruff format --check, ESLint)
- test: exit 0. Before my new file: test-py 384/384, test-gjs 1/1, test-ui 3/3. With my new file `tests/unit/test_jsonrpc_edge3.py`: test-py 393/393, test-gjs 1/1, test-ui 3/3. The UI tests ran on Chromium because Playwright WebKit lacks `libevent-2.1.so.7`.

## Done-when criteria
- [x] `printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' | .venv/bin/python tests/fakes/fake_acp_agent.py --scenario echo` prints one JSON line with `"protocolVersion": 1` and exits 0.
- [x] `make test` exits 0, including all tester edge-case files (edge 15, edge2 10, edge3 9 tests).

## Problems from attempt 2
- With DEBUG logging, a valid line nested 5000 deep killed the connection. This is fixed: `_log_text` catches `RecursionError` and logs a placeholder. `pytest tests/unit/test_jsonrpc_edge2.py -k very_deep` passes 2/2. The implementer added regression tests in `tests/unit/test_jsonrpc.py` (deep notification with DEBUG, deep handler result with DEBUG).
- Suggestion: NaN in a handler result. This is fixed with `allow_nan=False`, and `test_nan_handler_result_gets_an_internal_error` passes.
- No tests were skipped or weakened. The edge files from attempts 1 and 2 are unchanged.

## Tests added
- `tests/unit/test_jsonrpc_edge3.py` (9 tests, all pass). Each of the first four cases runs once at INFO and once at DEBUG:
  - a top-level array nested 5000 deep, which is not an object and is shown with `repr()`, is skipped, and the pending request is still answered;
  - a response whose `id` is nested 5000 deep is ignored;
  - a request whose `id` is nested 5000 deep gets a reply, and a later request is answered;
  - an error response with a `message` nested 5000 deep raises `JsonRpcError` with the right code, and the connection serves the next request;
  - `request()` with `inf` in its params raises `ValueError` and leaves no pending entry.

## Exploratory checks
- I drove `JsonRpcConnection` with a probe script, using the same deep or invalid lines as the tests, at both log levels. In every case the pending request was answered and the connection stayed open.
- No processes were left running.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
1. A request line with `"id": NaN` or `"id": Infinity` gets no reply. It also leaves "Task exception was never retrieved" with a `ValueError` traceback in the log. `json.loads` accepts these constants even though they are not JSON. The -32603 fallback in `_handle_request` then fails to encode the id a second time.
   - Effect: the connection keeps working, and the line comes from a peer that is not sending valid JSON, so this does not block the task.
   - Reproduce: send `{"jsonrpc":"2.0","id":NaN,"method":"x"}`.
   - Possible fix: pass `parse_constant` to `json.loads` in `_dispatch_line` so that such lines are rejected and skipped like any other non-JSON line.
2. `make test-py` prints `rm: nie można usunąć '/tmp/ai-panel-test-runtime.*/doc': Jest katalogiem` during cleanup. The runtime directory is left in `/tmp`. This comes from the Makefile and is outside this task.
