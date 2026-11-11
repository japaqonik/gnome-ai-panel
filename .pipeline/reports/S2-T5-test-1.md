# Test report S2-T5 attempt 1
Verdict: FAIL

## Command results
- build: ok (exit 0)
- lint: ok (ruff check, ruff format --check, ESLint; schema check skipped because `extension/schemas` does not exist yet). Lint also passes with my new test file.
- test (before my tests): ok. pytest 554/554, gjs 1/1, Playwright 3/3 (Chromium fallback, WebKit is missing `libevent-2.1.so.7`; this was already the case).
- test-py (with my tests): 570/571. The one failure is `test_cli_chat_signals.py::test_cancel_after_zero_cancels_immediately` (Problem 1).
- No `fake_acp_agent` process was left after `make test`, `make test-py` or any manual run (`pgrep -af fake_acp_agent` was empty each time).

## Done-when criteria
I ran these with `HOME`/`XDG_*` pointing to a temp dir.
- [x] `chat fake-echo 'Cześć'` gives stdout `Echo: Cześć` and make rc 0.
- [x] `test-agent fake-echo` prints `Agent: Fake ACP Agent (fake-acp-agent) 1.0.0`, `protokół: 1`, `metody logowania: brak` and `OK: …`, make rc 0.
- [x] `test-agent fake-missing` prints `Test połączenia nie powiódł się: Nie znaleziono polecenia: /nonexistent/agent` plus a hint. make rc is 2, and `.venv/bin/python -m app.cli` also exits exactly 2.
- [x] UAT-S2-1: `--json` prints 3 `text_delta` lines and the last line is `{"type": "done", "stop_reason": "end_turn"}`, rc 0.
- [x] UAT-S2-2: `fake-missing`, `fake-badver` and `fake-auth` give three different Polish messages (command not found / `Nieobsługiwana wersja protokołu ACP: 99 (obsługiwana: 1)` / login required with `Fake login`). The exact CLI exit code is 2 each time, with no traceback.
- [x] UAT-S2-4: `chat fake-env SECRET_VAR` prints `s3cr3t-value`. `grep -r s3cr3t-value $XDG_STATE_HOME/gnome-ai-panel/` exits 1, both at the default level and with `AI_PANEL_LOG_LEVEL=DEBUG`. In the DEBUG log the agent's reply chunk appears as `"text": "[redacted]"`, and stderr does not contain the secret either.
- [x] The tests listed in the task exist: every agent as a subprocess, valid JSON on every line, deny as the default, `--cancel-after 0.5` on slow giving `cancelled`, and an unknown ID giving 2 plus the agent list.

## Exploratory checks (exact CLI exit codes)
- Permissions: the default deny prints `[permission] … → odrzucono (domyślnie; …)`, and the agent then answers "Odmowa". `--permission allow --json` prints `permission_response` with `allowed: true`. `--permission maybe` is an argparse error, rc 2.
- Other event types: `fake-tool` prints `[thinking]`/`[tool]` lines; `fake-usage` prints a `[usage]` line with the cost. `fake-crash` exits 2 with `kod 3` and `boom` on stderr. `fake-noise`, `fake-load` and `fake-image` exit 0. `fake-crash-once` crashes on the first run and works on the second.
- `--cancel-after` input: `-1`, `nan`, `inf`, `abc` and `1e400` are rejected with rc 2. `0.001` through `0.1` give `cancelled` in about 0.42 s. `0` is ignored; see Problem 1.
- Signals: SIGINT during a slow chat (text and `--json`) gives rc 130 and `błąd: przerwano.`, and the agent process exits. SIGTERM gives rc 143 and also leaves no agent behind.
- Configuration: an unknown ID, or a missing config file (`Brak skonfigurowanych agentów.`), gives rc 2 for both commands. An empty prompt and a missing PROMPT argument behave as expected.
- I found no traceback for any agent in either `chat` or `test-agent`.

## Tests added
- `tests/integration/test_cli_chat_signals.py` (17 tests):
  - Ctrl+C (SIGINT) during `chat fake-slow`, in text and `--json` mode: rc 130, `przerwano`, no traceback, valid JSON lines, and no agent process left.
  - No agent process remains after chat with echo, crash, auth, badver, slow + `--cancel-after 0.3` and perm, or after test-agent with auth, badver and crash. Processes are found by their cwd under the isolated cache.
  - The secret is not in the log or stderr at the default level. With `--json` and with `test-agent fake-env` at DEBUG, it is in neither the log nor the output of test-agent.
  - `--cancel-after 0` must give `cancelled`. **This test fails** (Problem 1).
  - `--cancel-after 30` on echo still ends with `end_turn`.
  - A missing PROMPT is a usage error (rc 2) and starts no agent.
  - A Unicode, multi-line prompt works.

## Problems (for the implementer; each actionable)
1. **`--cancel-after 0` is accepted but does not cancel anything.**
   - Reproduce: `AI_PANEL_CONFIG=tests/data/config_fake.toml .venv/bin/python -m app.cli chat fake-slow x --json --cancel-after 0 | tail -1`
   - Expected: `{"type": "done", "stop_reason": "cancelled"}` right away.
   - Actual: `{"type": "done", "stop_reason": "end_turn"}` after the whole 10.2 s turn. `0.001` works.
   - Cause: in `app/cli.py` `run_chat`, the `_cancel_later` task is created before `backend.send()` has registered the turn. With a delay of 0 it runs `backend.cancel()` while `session.turn is None`, and `AcpBackend.cancel` (`app/backends/acp.py:384`) silently returns. The same race can hit any delay shorter than the time needed to send the prompt.
   - Fix: start the timer only once the turn is active (for example, after `send()` has started or the prompt request has gone out). Alternatively, remember the cancel request and apply it when the turn starts. You could also reject 0 in `seconds()`, but then the error text "nieujemnej liczby sekund" must change.
   - Regression test: `tests/integration/test_cli_chat_signals.py::test_cancel_after_zero_cancels_immediately`.

## Suggestions (non-blocking)
- When `--json` is interrupted with Ctrl+C, the last line is a `text_delta`, not a `done` or `error` line. The README says the last line is `done` or `error`. Either emit `{"type":"error","kind":"interrupted",…}` or document the exception.
- `test-agent` prints its failure message to stdout, while `chat` prints errors to stderr as `błąd: …`. This is consistent with the README, but scripts may expect errors on stderr.
- `[options]` only appears for `config_option_update` events. The `configOptions` from the `session/new` reply (`fake-models`) are not printed, although the README lists `[options]` among the session options.
- The real home already contains `~/.cache/gnome-ai-panel-fake/{echo,missing}`, created at 18:15 by the implementer's manual Done-when run. I did not remove them.
- `app.log` is created with mode 0664 (the directory is 0700, so this is low risk). This dates from S1.
