# Implementation report S4-T4 attempt 1

## Changes
- `app/backends/base.py`: `Backend` gained `config_options(session_id)`. `set_option` now returns the complete new option list (or `None`).
- `app/backends/acp.py`: `_Session` keeps the session's `configOptions`. They are filled from `session/new` and from the `session/set_config_option` answer (ACP returns the full list there), and also from `config_option_update`, which is stored even outside a turn. `set_option` has a timeout (`startup_timeout_s`). The old version waited forever.
- `app/controller.py`:
  - `select_agent(id)`: an unknown id is refused and `init` is sent again. Choosing the current agent is a no-op. Any other agent stops the turn and runs `new_chat`, then sends `init` with the new `current` and calls `on_agent_changed`. The controller drops its backend reference only; the old agent's process stays in the registry until `quit`.
  - `normalize_config_options`: only `select` options with valid fields reach the page (flat or grouped values). Lengths and counts are capped.
  - `config_options` is dispatched after session creation, on `ConfigOptions` events and after `set_option`.
  - `set_option(config_id, value)` forwards only an option and value the session offered. On failure it sends the unchanged `config_options` plus `notice {kind: "option_failed"}`. Late answers from an older conversation or session are dropped.
  - Options are dropped on new chat, on a crash and when a cancel is abandoned.
  - New properties `agents` and `config_options`.
- `app/bridge.py`: routes `select_agent {id}` and `set_option {config_id, value}`. Both are checked as non-empty strings of at most 256 characters; anything else is dropped with a warning. They were removed from `LATER_TYPES`.
- `app/main.py`:
  - New stateful action `agent`: parameter `s`, state `s`. Both activate and SetState call `select_agent`.
  - New read-only action `agents`: state `a(ss)`.
  - `_sync_agent_actions` sets both states at startup and is the controller's `on_agent_changed` callback.
- `app/strings.py`: new texts `CTRL_OPTION_FAILED` and `ACP_REQUEST_TIMEOUT`.
- `app/ui/index.html`, `chat.js`, `strings.js`, `style.css`:
  - The header has `select#agent` (a change posts `select_agent`; the next `init` sets the value, so a refused change is undone), `select#model` and `#mode-badge`.
  - `select#model` is shown only for the first `select` option with `category == "model"`. Groups become `<optgroup>`s. A current value the agent does not list is still shown. A change posts `set_option` and disables the select until the next `config_options`. `conversation` and the empty screen hide it.
  - `#mode-badge` with `data-mode` `tools` (amber, "Agent z narzędziami") or `chat` (green, "Czysty czat"), with light and dark colours.
  - All texts go in through `textContent`.
  - `init` drops agent entries without a string id.
- `tests/fakes/fake_acp_agent.py`: `--record` also records `session/set_config_option`.
- Tests added:
  - `tests/unit/test_controller_agents.py` (23 tests: normalization including groups and caps, select_agent, the api agent, set_option success/failure/stale answer, `config_option_update`, crash).
  - `tests/integration/test_controller_models_acp.py` (3 tests: the real fake `models` agent, `session/set_config_option` recorded with the correct params, the `currentValue` update, the next reply uses `[fake-large]`).
  - `tests/integration/test_agent_actions.py` (5 GUI tests: `agents`/`agent` states, activate and SetState, an unknown id ignored, an api agent gets the `chat` badge and the unsupported error).
  - `tests/ui/header.spec.mjs` (16 tests).
  - New cases in `tests/unit/test_bridge.py` and `tests/unit/test_actions.py`.
- Tests adapted to the new header: `#agent-name` became `select#agent` in `chat.spec.mjs`, `chat-edge.spec.mjs` and `test_chat_window.py`. The parametrize in `test_bridge.py` uses `history_list` as the unhandled type now that `select_agent` is handled. The expected action list in `test_actions.py` grew. Fake backends in the tests got `config_options`. No assertion was weakened: the malformed-agents test now checks the stricter behaviour (no valid id → empty screen).
- `README.md`: the `agent`/`agents` actions, the header behaviour, the ui-dump fields `agent` and `badge`, a try-it block and a developer section.

## Problems from previous report
- No test report for S4-T4 exists. The S4-T3 test report listed no problems.

## How to verify
- `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml make run-headless && source .run/headless.env`
  - `gapplication action pl.local.AiPanel agent "'fake-models'"`, then `gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.Describe agent` → `((true, signature 's', [<'fake-models'>]),)`
  - `gdbus call … Describe agents` → `[('fake-echo', 'fake-echo'), …]`
  - `debug-send "'a'"`, then `make -s cli ARGS="ui-dump"` → `agent: "fake-models"`, `badge: "tools"`, reply `[fake-small] Echo: a`
  - `make stop`
  - Checked this way; no processes were left behind.
- `PW_BROWSER=chromium npx playwright test tests/ui/header.spec.mjs` → 16 passed

## Command results
- build: ok
- lint: ok
- test (`PW_BROWSER=chromium make test`): test-py 833/833, test-gjs 1/1, test-ui 136/136 (Chromium; Playwright WebKit cannot launch on this machine, as in earlier stages)

## Known limitations / deviations from plan
- The `agents`/`agent` states are set at startup and on every agent change. The config hot reload (FR-22, S8-T1) does not exist yet; it should call `_sync_agent_actions` (the controller's `on_agent_changed` hook) after a reload.
- The model list appears only after the first prompt: sessions start lazily, and `configOptions` arrive with `session/new`. Creating a session as soon as an agent is selected would start the agent process early, so I left it out of this task.
- Only the first `category == "model"` select is shown. Other options (mode, `model_config`, boolean) are not shown; boolean ones are not advertised in `clientCapabilities` either, so agents must not send them.
- An agent change during a running turn ends it with `done cancelled`. The backend then sends `session/cancel` to the old agent when the iterator closes.
- Choosing an api agent works (the badge reads "Czysty czat"), but `send` gives the existing `CTRL_AGENT_UNSUPPORTED` error until S7.
