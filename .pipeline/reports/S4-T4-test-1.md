# Test report S4-T4 attempt 1
Verdict: FAIL

## Command results
- build: ok
- lint: ok (ruff check, ruff format --check, eslint, schema check)
- test (`PW_BROWSER=chromium make test`, before my additions): test-py 833/833, test-gjs 1/1, test-ui 136/136 (Chromium; Playwright WebKit cannot launch on this machine)
- My additions: `tests/unit/test_agents_edge.py` 4/4 pass; `tests/integration/test_models_acp_edge.py` 4/5 pass, `test_config_option_update_right_after_session_new_is_kept` fails in about 5 of 6 runs (bug below).

## Done-when criteria
- [x] Headless with `config_fake.toml`: `gapplication action pl.local.AiPanel agent "'fake-models'"` → `Describe agent` = `((true, signature 's', [<'fake-models'>]),)`; `ui-dump` → `agent: fake-models`, `badge: tools`. After `debug-send 'a'` the reply is `[fake-small] Echo: a`.
- [x] `Describe agents` → `[('fake-echo', 'fake-echo'), ('fake-thinking', …), …, ('fake-missing', 'fake-missing')]`
- [x] `PW_BROWSER=chromium npx playwright test tests/ui/header.spec.mjs` → 16 passed (as part of 136/136)
- [x] Listed tests exist and assert behaviour: no `config_options` → `#model` hidden; flat and grouped options → visible, `<optgroup>`s, change → `set_option`; agent change → `select_agent`; badge text, `data-mode` and colour by type (light and dark); integration `fake-models`: `session/set_config_option` recorded with `{sessionId, configId: "model", value: "fake-large"}`, `currentValue` updated, next reply `[fake-large]`.

## Exploratory checks (headless, all processes stopped with `make stop`, none left)
- `SetState agent <'fake-echo'>` switches the agent. `Activate agent` with `'nope'`, `''` and a 100 000-character id is ignored and the state stays.
- A wrong parameter type (`<42>`, no parameter) is rejected by GIO with `InvalidArgs`. `SetState agents …` is ignored (read-only).
- Switching from `fake-slow` to `fake-models` in the middle of a turn: `busy: false`, the conversation is cleared, and the next prompt answers `[fake-small] Echo: b`. No tracebacks in the log.

## Tests added
- `tests/unit/test_agents_edge.py`:
  - ids of exactly 256 characters are accepted by the bridge;
  - `select_agent` and `set_option` without a handler are dropped;
  - after an agent switch, `set_option` does not reach the old agent's backend and the page gets `config_options []`;
  - switching to another agent and back works, and the callbacks fire in order.
- `tests/integration/test_models_acp_edge.py` (real `AcpBackend` with a small inline agent):
  - a `session/set_config_option` that is never answered raises `timeout` within `startup_timeout_s`, and the controller then shows `notice option_failed` with the old value;
  - a `config_option_update` sent 0.3 s after `session/new` is kept;
  - a `config_option_update` sent right after the `session/new` answer is kept (**fails**);
  - an answer without `configOptions` returns `None` and keeps the stored list.

## Problems (for the implementer; each actionable)
1. **A `config_option_update` sent right after the `session/new` answer is lost.**
   - **Where:** `app/backends/acp.py`, `_on_notification` and `new_session`.
   - **Reproduce:** `.venv/bin/pytest -q tests/integration/test_models_acp_edge.py -k right_after`. It fails in about 5 of 6 runs.
   - **Expected:** `config_options(session_id)` reports `currentValue == "b"`, the value from the update.
   - **Actual:** it stays at `"a"`.
   - **Cause:** the JSON-RPC reader resolves the `session/new` future and then handles the next line, which is the notification, in the same loop pass. `new_session()` has not resumed yet, so `self._sessions` has no entry for the id and the update is dropped as "session/update of an unknown session ignored". Agents may send `session/update` for a session right after answering `session/new`, and real ACP agents do so with `available_commands_update`. In that case the model list shows a stale value.
   - **Suggested fix:** register the session before the reader can handle the next line, or buffer `session/update` notifications for unknown session ids on the same process and apply the latest `ConfigOptions` when `new_session` registers the session. The test should then pass every time; loop it 10 times or more.

## Suggestions (non-blocking)
- `select_agent` drops the controller's backend reference, but a session the old agent was still creating keeps running until `quit`. The result is discarded correctly, so this is only a small resource cost.
- The model list appears only after the first prompt (a known limitation, documented in the README).
