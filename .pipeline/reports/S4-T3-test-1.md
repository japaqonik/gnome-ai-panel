# Test report S4-T3 attempt 1
Verdict: PASS

## Command results
- build: `make build` exit 0
- lint: `make lint` exit 0 (ruff check/format, ESLint; schema check skipped, no `extension/schemas` yet)
- test: `PW_BROWSER=chromium make test` exit 0: test-py 791/791, test-gjs 1/1, test-ui 120/120 (Chromium, WebKit cannot launch on this machine)
  - The first full run had 1 failure: `tests/integration/test_debug_actions.py::test_external_link_goes_to_the_launcher` (from S3, not S4-T3). The test waited only until the URI log file existed, then read it before the app had written the line (`'' == 'https://example.com/\n'`). The race is in the test, not in production code: `app/window.py` opens the file in append mode and then writes. I fixed the test so it waits for a complete line. The second full run passed.

## Done-when criteria
- [x] Headless with `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-crash-once` (fresh `.run/home/.cache/gnome-ai-panel-fake`). Evidence: `debug-send "'a'"` → `ui-dump` messages `[user, error]`; the error has `kind: crashed` and text "Agent przestał działać / Proces agenta zakończył działanie (kod 3). / Ostatnie linie stderr agenta / boom / Następna wiadomość uruchomi agenta ponownie…". The stderr sits in a collapsed `<details>`. `debug-send "'b'"` → `[user, error, user, notice "Agent został uruchomiony ponownie, poprzedni kontekst utracony", assistant "Echo: b"]`. A third `debug-send "'c'"` → `Echo: c` with no second notice.
- [x] `make test` exits 0 (see above).
- [x] Tests listed in the task:
  - The unit test for each `Error.kind` → text is `test_controller_failures.py::test_every_error_kind_gets_title_and_hint`, parametrized over `ERROR_KINDS`.
  - The crash → restart → next turn integration test is `test_controller_failures_acp.py::test_crash_once_then_restart_and_next_turn`, plus `test_debug_actions.py::test_crash_then_restart_through_debug_send` over D-Bus.
  - The cancel with an `in_progress` tool → card `cancelled` test is `test_controller_failures_acp.py::test_cancel_with_in_progress_tool_marks_card_cancelled`, plus the Playwright tests in `failures.spec.mjs`.

## Exploratory checks (headless app)
- `fake-crash` with 6 prompts: p1 crashes. p2–p4 each show the restart notice and then crash. p5 gets the restart-limit card ("Agent ulegał awarii zbyt często (3 ponowne uruchomienia w ciągu 60 s)…"), and the prompt is disabled (p6 is not sent). After `new-chat`, a prompt within the same 60 s is blocked again, which is the documented behaviour.
- `slow-tool` (temporary config): while the turn runs, the tool is `in_progress`. `debug-click '#stop'` → within 0.3 s `busy: false`, the tool is `cancelled` and the reply ends with "Przerwano".
- `stubborn`: after stop the turn is still busy at 1 s and ended with "Przerwano" at 6 s (the 5 s watchdog). The next prompt shows the notice "Agent nie potwierdził przerwania…, więc rozpoczęto nową sesję…".
- `make stop` left no fake agent, app or Xvfb processes.

## Tests added
- `tests/unit/test_controller_failures_edge.py`:
  - repeated cancel → one backend cancel, one `cancelled` update per tool, one `done`, no leftover tasks
  - `new_chat` while waiting for a stubborn cancel → nothing of the old turn after `conversation`, no notice in the new conversation
  - cancel while the session is being created → immediate `done cancelled`, no backend cancel, no watchdog `done`
  - `crashed` stderr not present in the message → message unchanged
  - empty stderr is not shown
  - bad auth method entries are skipped and the list is capped at 20
  - a blocked error uses the restart-limit hint
- `tests/ui/failures-edge.spec.mjs`:
  - markup in the title, message, hint, auth methods and labels is shown as text
  - a notice with markup is shown as text and the reply follows it
  - an error/conversation without a running turn does not break the page
- `tests/integration/test_debug_actions.py`: fixed the read race in `test_external_link_goes_to_the_launcher`, which now waits for a complete line.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
1. While the agent is being restarted, the "Agent został uruchomiony ponownie" notice appears before each new crash (p2–p4 above). It is correct but noisy. Consider not repeating it when the previous turn also ended with `crashed`.
2. A `tool_update` that arrives after a cancel (before the agent's `done`) can overwrite the locally set `cancelled` status, e.g. with `completed`. That arguably shows the truth, but `_cancel_tools` on `done cancelled` will not mark it back. Decide whether this is intended and document it.
3. The working tree still holds uncommitted S4-T1/S4-T2 changes along with S4-T3, so the S4-T3 diff cannot be reviewed on its own.
