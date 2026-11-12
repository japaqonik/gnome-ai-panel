# Implementation report S4-T3 attempt 1

## Changes
- `app/backends/base.py`: new `RestartLimitError(BackendError)` so the controller can tell "restart refused" apart from other `crashed` errors.
- `app/backends/acp.py`: `_check_restart_limit` raises `RestartLimitError` (same `Error` event as before, kind `crashed`).
- `app/strings.py`: chat texts `CHAT_ERROR_TITLES` (every `Error.kind`), `CHAT_ERROR_HINTS` (`spawn`, `timeout`, `protocol`, `auth` with "Zaloguj się w terminalu, np. poleceniem logowania swojego agenta", `crashed`), `CHAT_AUTH_*`, `CHAT_RESTART_LIMIT_HINT`, `CHAT_STDERR_LABEL`, `CTRL_AGENT_RESTARTED` ("Agent został uruchomiony ponownie, poprzedni kontekst utracony"), `CTRL_SESSION_ABANDONED`, `CTRL_BLOCKED`.
- `app/controller.py`:
  - `error_event(Error, blocked=)` builds `error {kind, title, message, hint, stderr, stderr_label, auth_methods, methods_label, blocked}`; for `crashed` the stderr tail is cut from `message` and sent as `stderr`; for `auth` the methods become `["name: description", …]`.
  - `cancel()` dispatches `tool_update {status: cancelled}` at once for pending/in-progress tools (also on `done cancelled` from the agent, without repeats), and starts a watchdog.
  - Watchdog (S3-T3 open issue): if the backend has not ended the cancelled turn after `CANCEL_TIMEOUT_S = 5` s (`cancel_timeout_s=` parameter), the controller ends it with `done cancelled`, cancels the turn task (closes the backend iterator) and drops the session, so the next prompt does not go to a session the agent may still be busy with. The watchdog is cancelled when the turn ends normally.
  - After a `crashed` error in a turn, the next new session is preceded by `notice {kind: "context_lost", text}`; after an abandoned cancel the same with `CTRL_SESSION_ABANDONED`. No notice when the agent failed before any session existed.
  - `RestartLimitError` → `error` with `blocked: true`; afterwards every `send` is answered with a blocked `error` until `new_chat` (which clears the block and any pending notice).
- `app/ui/chat.js`, `strings.js`, `style.css`: stop marks unfinished tool cards `cancelled` immediately and disables `#stop` until the next turn; `done cancelled` marks them too; error card with title/message/hint, auth method list, collapsed `<details class="message__stderr">` for stderr (all via `textContent`); an empty reply of a failed turn is removed; `notice` handler (inserted before the running reply, `role="status"`, dump role `notice`); blocked error disables prompt and send, adds a "Nowa rozmowa" button posting `new_chat`; `conversation` unblocks.
- `tests/fakes/fake_acp_agent.py`: scenarios `slow-tool` (tool call in progress, not updated on cancel) and `stubborn` (ignores `session/cancel`).
- Tests: `tests/unit/test_controller_failures.py` (every `Error.kind` → title/hint, stderr/auth formatting, restart notice, restart-limit block, immediate tool cancel, watchdog), `tests/integration/test_controller_failures_acp.py` (real agent: crash-once → restart → next turn, restart limit → block → new_chat, cancel with `in_progress` tool → card `cancelled`, stubborn agent → turn ends after timeout, new session in the same process), `tests/integration/test_debug_actions.py::test_crash_then_restart_through_debug_send` (the "Done when" scenario through D-Bus), `tests/ui/failures.spec.mjs` (10 Playwright tests). `tests/unit/test_controller.py::test_session_error_is_reported_and_retried` updated to the new error shape.
- `README.md`: cancel/errors/restart behaviour with a runnable example, developer notes on the new events and fake scenarios.

## Problems from previous report
- No previous S4-T3 report. Open issue from S3-T3 ("agent ignoring session/cancel never ends the turn") → fixed with the controller watchdog (see above), covered by unit and integration tests (`stubborn` scenario).

## How to verify
- `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-crash-once make run-headless && source .run/headless.env`
- `gapplication action pl.local.AiPanel debug-send "'a'"`, `make -s cli ARGS="ui-dump"` → last message `role: error`, `kind: crashed`, text contains `kod 3` and `boom` (checked manually: yes)
- `gapplication action pl.local.AiPanel debug-send "'b'"`, `ui-dump` → `notice` "Agent został uruchomiony ponownie, poprzedni kontekst utracony", then assistant `Echo: b` (checked manually: yes); `make stop`
- `make test` → exit 0

## Command results
- build: ok, lint: ok, test: test-py 784/784, test-gjs 1/1, test-ui 117/117 (Chromium fallback on this machine)

## Known limitations / deviations from plan
- PLAN §12.2 lists `error {message, kind}`; the event now carries extra fields (`title`, `hint`, `stderr`, `stderr_label`, `auth_methods`, `methods_label`, `blocked`) and there is a new Python → JS event `notice {kind, text}`. Older consumers that read only `message`/`kind` still work.
- The CLI (`chat`, `test-agent`) is unchanged: it still prints the backend's full message (stderr included), as before.
- The restart window lives in the backend; after `new_chat` the block is lifted, but a restart within the same 60 s window is refused again (the card then reappears). This follows the plan's 3/60 s limit.
- After the cancel timeout the agent may still be running the abandoned prompt in its old session; its later updates are ignored. The process is not killed (it may be serving other sessions).
