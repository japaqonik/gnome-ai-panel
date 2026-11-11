# Test report S2-T4 attempt 1
Verdict: PASS

## Command results
- build: `make build` → exit 0
- lint: `make lint` → exit 0 (ruff check, ruff format, ESLint; schema check skipped, no `extension/schemas` yet)
- test: `make test` → exit 0. test-py 468/468 (459 from the implementer plus 9 added by me), test-gjs 1/1, test-ui 3/3 (Chromium fallback: Playwright WebKit lacks `libevent-2.1.so.7` on this host)
- The 12 pytest warnings come from earlier tasks (`gi/events.py` DeprecationWarnings in `test_asyncio_glib.py` and `test_secrets_edge.py`). None come from S2-T4 code.

## Done-when criteria
- [x] `make test` → exit 0. Evidence: run twice, both exit 0 (`459 passed` before my tests, `468 passed` after).
- [x] AcpBackend integration tests take ≤ 30 s in total. Evidence: `xvfb-run -a dbus-run-session -- .venv/bin/pytest -q tests/integration/test_acp_backend.py tests/unit/test_acp_mapping.py --durations=8` → `66 passed in 5.95s`; the slowest test is `test_startup_timeout_kills_the_process` at 1.00 s. With my edge tests: `test_acp_backend.py` + `test_acp_backend_edge.py` → `50 passed in 7.74s`.
- [x] No agent processes left after the tests. Evidence: `ps -eo pid,stat,args | grep -E "[f]ake_acp_agent|[s]leep 30|[r]unpy"` after the full `make test` and after the targeted runs → no match (rc 1). The new edge tests also check that every PID the backend spawned is gone, on every failure path.
- [x] The test list from TASKS.md is covered in `tests/integration/test_acp_backend.py`: echo (order and content of the deltas, `end_turn`), thinking, tool (ToolCall + 2 ToolUpdate), permission allow/reject, slow + cancel ≤ 2 s, crash (`boom`, restart), bad-version, auth, noise, missing command (absolute path and bare name), startup timeout (`sleep 30`, 1 s), two parallel sessions with routing, `mcpServers`/`_meta` via `--record`, secret via `env`.

## Tests added
- `tests/integration/test_acp_backend_edge.py` (9 tests, about 1.9 s, all pass):
  - startup timeout: the `sleep 30` process is really gone (PID captured by wrapping `create_subprocess_exec`), not just `backend.pid is None`;
  - failed `initialize` (bad-version) leaves no process;
  - an auth error followed by `close()` leaves no process;
  - processes that crashed and were restarted are all reaped;
  - `close()` kills a grandchild (`sleep 30`) in the agent's process group;
  - the stderr tail is limited to the last 20 lines (30 written; lines 11–30 kept, in `Error.stderr` and the message);
  - agent killed with SIGKILL while idle: `send` on the old session gives `crashed`, the next `new_session` restarts it and echo works;
  - `close()` while a permission request is open ends the turn, and the process is gone;
  - a relative `cwd` is created and sent as an absolute path in `session/new`.

## Code review
- `app/backends/acp.py` follows the task scope: no shell, `start_new_session=True`, `cwd` 0700, the version check rejects `bool`, `fs/*`/`terminal/*` requests get -32601, secrets are not logged (the MCP env redaction test passes), and SIGTERM → 3 s → SIGKILL goes to the whole process group.
- No tests were skipped or weakened. No hardcoded secrets. No scope creep beyond the task: the registry and the `BackendError` deviation are documented.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
1. `_session_params` resolves MCP commands without `/` through the app's `PATH` (`shutil.which(command)`), not the agent environment's `PATH`, which `_program` uses for the agent command. If an agent's `env` overrides `PATH`, the two lookups give different results.
2. After `close()`, `send()` on a former session yields kind `crashed` ("session lost"). Kind `other`/closed would describe this case better for the UI in S4-T3.
