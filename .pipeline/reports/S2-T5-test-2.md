# Test report S2-T5 attempt 2
Verdict: PASS

## Command results
- build: ok (exit 0)
- lint: ok (ruff check, ruff format --check, ESLint; schema check skipped because `extension/schemas` does not exist yet), also with my new test file.
- test: ok. pytest 572/572, gjs 1/1, Playwright 3/3 (Chromium fallback; WebKit is missing `libevent-2.1.so.7`, which was already the case).
- test-py with my new tests: 578/578.
- No `fake_acp_agent` process was left after `make test`, `make test-py` or the manual runs (`ps -eo pid,args | grep fake_acp_agent` was empty).

## Done-when criteria
I ran these with `HOME`/`XDG_*` pointing to a temp dir.
- [x] `chat fake-echo 'Cześć'`: stdout `Echo: Cześć`, make rc 0.
- [x] `test-agent fake-echo`: `Agent: Fake ACP Agent (fake-acp-agent) 1.0.0`, `protokół: 1`, `OK: …`, make rc 0.
- [x] `test-agent fake-missing`: `Test połączenia nie powiódł się: Nie znaleziono polecenia: /nonexistent/agent` plus a hint. make rc 2; `.venv/bin/python -m app.cli` exits exactly 2.
- [x] UAT-S2-1: `--json` prints 3 `text_delta` lines, and the last line is `{"type": "done", "stop_reason": "end_turn"}`, rc 0.
- [x] UAT-S2-2: missing / badver / auth give three different Polish messages (command not found; `Nieobsługiwana wersja protokołu ACP: 99 (obsługiwana: 1)`; `Agent wymaga zalogowania. Dostępne metody: Fake login …`). The exact CLI rc is 2 each time, with no traceback.
- [x] UAT-S2-4: `chat fake-env SECRET_VAR` prints `s3cr3t-value`, rc 0. With `AI_PANEL_LOG_LEVEL=DEBUG`, `grep -r s3cr3t-value $XDG_STATE_HOME/gnome-ai-panel/ <stderr file>` exits 1.
- [x] Unknown ID: rc 2, and stderr lists all 16 agents.

## Fix verification (problem 1 from test-1)
- [x] `--cancel-after 0` now cancels: 20 out of 20 runs at the default log level and 10 out of 10 at DEBUG ended with `{"type": "done", "stop_reason": "cancelled"}`. Text mode ends with `[done] cancelled`. `--cancel-after 0.5` cancels after 3 fragments in 0.8 s. `fake-perm --cancel-after 0` ends with `cancelled`, and `fake-crash --cancel-after 0` exits 2 with `kod 3`/`boom`.
- [x] Regression tests: the original `test_cancel_after_zero_cancels_immediately`, the implementer's unit test `test_run_chat_cancel_after_zero_cancels_running_turn`, and my tests below all pass.
- Code review: in `AcpBackend.send` everything up to `session.turn = turn` runs without an `await`, so a single `asyncio.sleep(0)` is enough for the consumer task to register the turn. The fake agent now clears the cancel flag when the prompt is read, which matches ACP message order. I also checked that a cancel sent before a prompt does not cancel that prompt (test below).

## Tests added
- `tests/integration/test_cli_cancel_race.py` (6 tests):
  - `--cancel-after 0` five times in a row, at the default level and at DEBUG (the race depended on timing): each run ends with `cancelled` in under 5 s.
  - `--cancel-after 0` in text mode ends with `[done] cancelled`.
  - `--cancel-after 0` on `fake-perm` while a permission request is pending: `cancelled`, rc 0, no agent process left.
  - Fake agent driven directly: `session/prompt` and `session/cancel` in a single write give `cancelled`.
  - Fake agent driven directly: a `session/cancel` before the prompt does not affect it (`end_turn`).

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
- Carried over from attempt 1, the implementer explained why each is out of scope:
  - An interrupted `--json` run has no final `done`/`error` line.
  - `configOptions` from `session/new` are not printed as `[options]`.
  - `app.log` is created with mode 0664; a later task should create it with 0600.
- `~/.cache/gnome-ai-panel-fake/{echo,missing}` still exist in the real home, left over from the first implementation run. They can be removed with `rm -r ~/.cache/gnome-ai-panel-fake`.
