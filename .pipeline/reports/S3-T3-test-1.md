# Test report S3-T3 attempt 1
Verdict: PASS

## Command results
- build: ok (exit 0)
- lint: ok (ruff check, ruff format --check, ESLint; schema check skipped, no schemas yet)
- test, first run: exit 2. `tests/integration/test_acp_backend_edge.py::test_close_kills_children_in_the_process_group` failed with `ProcessLookupError` inside the test helper `process_gone()`. This is a race in a helper from S2-T4 (`kill(pid, 0)` succeeds, then the process is reaped before `/proc/<pid>/stat` is read, which raises ESRCH). The product code did what it should: the child was already gone. I fixed the helper (test file only) to treat `ProcessLookupError` like `FileNotFoundError`.
- test, second run (with the fix and my new tests): exit 0. pytest 639/639, GJS 1/1, Playwright 59/59 (Chromium fallback, because WebKit is missing host libraries; documented).
- After both `make test` runs, `pgrep -af "fake_acp_agent|sleep 30|python -m app"` found nothing.

## Done-when criteria
- [x] `make test` → exit 0. Evidence: second run above.
- [x] Tests listed in TASKS (unit tests with FakeBackend and a list sink): dispatch order, send during a turn rejected, cancel → `backend.cancel`, backend Error → `error` and the next turn works, no agents → `init.agents == []`, `new_chat` → new `new_session`, bridge ignores a message without `type`, `</script>`/U+2028 are escaped. Evidence: all present in `tests/unit/test_controller.py` and `tests/unit/test_bridge.py`, and all pass.
- [x] UI contract: every `send` gets exactly one `done`/`error`, including rejected sends (busy, empty, no agent, `api` type, invalid `send` in the bridge). Evidence: implementer tests plus my `test_mixed_sequence_keeps_contract` and `test_echo_turns_and_rejected_send_keep_contract`, which uses the real agent.
- [x] No `text_delta` after `done`. Evidence: scripted text after `Done`/`Error` is not dispatched. With the real `fake-slow` agent, I waited 0.6 s after a cancel and no events came (the agent sends a chunk every 200 ms). The same holds after `new_chat` in the middle of a turn.
- [x] Repeated `cancel` is idempotent. Evidence: 3 or 5 cancels give one `backend.cancel`. With the real agent, 4 cancels give exactly one `done cancelled`. When `backend.cancel` raises, the error is logged and the turn still ends.
- [x] `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml make run-headless` → `run-headless: ui ready`. The log shows `16 agent(s), 0 error(s)`, `agent: fake-echo` and `ui ready`. `new-chat` logs `new chat`. With an invalid `AI_PANEL_DEFAULT_AGENT=nope`, a warning is logged and the app falls back to `fake-echo`.
- [x] `make stop` → app, dbus-daemon and Xvfb stopped, `quit requested` in the log (graceful). No ERROR or Traceback in the log. Afterwards no app, Xvfb or fake agent processes, and no `/tmp/ai-panel-runtime.*` left. Note: the headless app has no way to start a turn before S3-T4 (`debug-send`), so the agent cleanup at quit was checked in-process instead (`close()` + `close_all()`, see the tests below).

## Tests added
- `tests/unit/test_controller_edge.py` (9 cases):
  - text after `Done` or after `Error` in the stream is not dispatched;
  - a send after cancel but before the agent's `done` is rejected with one `error`;
  - a send right after a cancel during session creation reuses the pending session (one `new_session`, no `backend.cancel`);
  - `new_chat` during session creation does not adopt the old session, and the next send creates `s2`;
  - repeated `new_chat` during a turn gives one `done`;
  - `cancel` after `close()` dispatches nothing;
  - a failing `backend.cancel` is logged and the turn still ends;
  - a mixed sequence of sends, busy sends and repeated cancels keeps the contract.
- `tests/integration/test_controller_acp.py` (3 cases, ChatController with the real AcpBackend and the fake agent):
  - repeated cancel of a `slow` turn gives one `done cancelled` and no later events, and the next turn works;
  - `new_chat` in the middle of a turn gives no late chunks, the next send gets a new session on the same process, and the agent PID is gone after `close_all()`;
  - `echo` turns with a rejected empty send between them give `done`, `error`, `done`, and the agent PID is gone after close.
- `tests/integration/test_acp_backend_edge.py`: fixed the `process_gone()` race (ESRCH while reading `/proc/<pid>/stat`).

I ran the new tests and the fixed file 5 times in a row: 21/21 passed each time.

## Problems (for the implementer; each actionable)
None blocking.

## Suggestions (non-blocking)
1. A `send` rejected because a turn is running is answered with `error` in the middle of the running turn. The page (`chat.js` `onError`) treats any `error` as the end of the turn, so the running turn's later `text_delta`s would open a new assistant bubble. The page never posts `send` while busy, so this cannot happen today. It can happen once a non-UI path calls `controller.send` (for example if `debug-send` in S3-T4 bypasses the page's busy check). Options: give the rejection a distinct `kind` (e.g. `busy`) that the page shows without ending the turn, or make `debug-send` go through the page as PLAN §12.1 says ("wpisuje tekst i wysyła"). `test_send_after_cancel_but_before_done_is_rejected` checks only the count for this case.
2. `ChatController.send` catches only `NotImplementedError` from the backend factory. Any other exception would escape to the bridge and leave the page waiting with no `done`/`error`. `get_backend` cannot raise anything else today, but catching `Exception` there and answering with `CTRL_UNEXPECTED` would make the contract unconditional.
3. `tests/integration/test_run_scripts.py::_alive` has the same race as the helper I fixed (`stat.exists()` and then `read_text()`). It has not failed yet.
4. If the agent ignores `session/cancel`, the turn never ends and the UI stays busy. A timeout fallback could be added in S4-T3 (cancellation work).
