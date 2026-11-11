# Implementation report S3-T3 attempt 1

## Changes
- `app/controller.py` (new, no GTK): `ChatController(config, ui_sink, backend_factory, *, default_agent=None)`.
  - Agent choice (`choose_agent`): the override (`AI_PANEL_DEFAULT_AGENT`) if valid, else `default_agent`, else the first valid agent, else `None`.
  - `ready()` dispatches `init {agents, current, config_errors, theme, font_size}`. With no agents, `agents == []`.
  - `send()` creates the backend and the session lazily (`new_session` at the first prompt, then reused) and dispatches `turn_start`, `text_delta`…, then `done`/`error`.
  - `cancel()`, `new_chat()` (new conversation, the next send creates a new session, dispatches `conversation {id: null, messages: []}`) and `close()`.
  - The conversation is kept in `messages` in memory.
  - UI contract: (a) every `send` gets exactly one `done` or `error`, also a rejected one (turn running, no agent, unsupported `api` type, empty prompt); (b) `_finish()` marks the turn finished and `_emit()` drops anything after that; (c) `cancel` is idempotent (`cancel_requested`), so `backend.cancel` is called once.
  - A cancel while the session is still being created ends the turn at once with `done cancelled`. Session creation is shielded and goes on, and the next turn reuses that session.
  - A `crashed` error drops the session id. A `BackendError` from `new_session` becomes `error`, and the next send retries. Unexpected exceptions become a generic error, and the details go only to the log.
  - `PermissionRequest` is rejected (`respond_permission(id, None)`) until the dialog exists (S4-T2).
- `app/bridge.py`:
  - Field validation of `send` (`text` must be a string; `images`, if present, a list of `{type:"image", mimeType, data}`). An invalid `send` is answered with `error`, so the UI is never left in the turn state.
  - Routes `ready`/`send`/`cancel`/`new_chat` to the handler. Later-stage types and unknown types are logged at WARNING and dropped.
  - `dispatch()` runs `evaluate_javascript("window.aiPanel.dispatch(" + json + ")")`. `dispatch_script()` uses `ensure_ascii` (so U+2028/2029 are escaped) and also escapes `<`, `>` and `&`, so `</script>` cannot appear.
  - `attach()` now takes the WebView.
- `app/window.py`: `bridge.attach(self.webview)`.
- `app/main.py`:
  - Loads the configuration at startup (`load_config()`, which uses `AI_PANEL_CONFIG`/XDG) and builds `ChatController` with `get_backend(agent, mcp=config.mcp)`. `AI_PANEL_DEFAULT_AGENT` is passed as the override.
  - The `new-chat` action calls `controller.new_chat()`.
  - `quit` and SIGTERM run `controller.close()` + `backends.close_all()` (bounded by a 5 s timeout) before `quit()`, so agent processes are stopped.
- `app/strings.py`: `CTRL_*` texts.
- `app/ui/chat.js`: handler for `conversation`. It clears the message list and returns to idle. This is needed so that `new-chat` is visible in the UI.
- Tests:
  - `tests/unit/test_controller.py` (27 tests, FakeBackend with a scripted event list and a list `UiSink`): dispatch order, lazy and reused session, send during a turn rejected with `error`, a single `backend.cancel` for 3 cancels, cancel during session creation, backend `Error` followed by a working next turn, `BackendError` from session creation, no agents → `init.agents == []`, no agent / unsupported type / empty prompt → `error`, `new_chat` → new `new_session`, `new_chat` during a turn sends no late events, no `text_delta` after the terminal event, `close`, a failing sink.
  - `tests/unit/test_bridge.py` (+16): routing, a message without `type` is ignored, invalid `send` → `error`, unknown/later types → WARNING, `dispatch_script` is safe for `</script>`, U+2028/2029 and `&`, and round-trips.
  - `tests/integration/test_chat_window.py` (gui, in-process): real WebKit page → bridge → controller → fake ACP agent. Covers a full turn with `fake-echo`, cancel (2 clicks) with `fake-slow` giving one `done cancelled` and no `text_delta` after it, the empty screen without a config, and `fake-missing` → error `kind=spawn`.
  - `tests/integration/test_app_controller.py` (gui, process): `AI_PANEL_CONFIG` + `AI_PANEL_DEFAULT_AGENT` are honoured, an invalid override falls back, `new-chat` reaches the controller, `quit` exits 0.
  - `tests/ui/chat.spec.mjs`: a test for `conversation`.
- `README.md`: status, agent choice and `new-chat`/`quit` behaviour, bridge/controller description.

## Problems from previous report
- S3-T2 test report: no blocking problems. Suggestions 1 and 2 (no `text_delta` after `done`, idempotent `cancel`) are implemented and tested (see above). Suggestions 3 (screen reader) and 4 (WebKit run) are outside this task.

## How to verify
- `make test` → exit 0.
- `.venv/bin/pytest -q tests/unit/test_controller.py tests/unit/test_bridge.py` → all pass.
- `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-slow make run-headless`, then `source .run/headless.env && gapplication action pl.local.AiPanel new-chat`. `.run/app.log` should show `agent: fake-slow`, `ui ready` and `new chat`. Then run `make stop`.

## Command results
- build: ok, lint: ok, test: pytest 627/627, GJS 1/1, Playwright 59/59 (Chromium fallback; WebKit is missing host libs, as documented).

## Known limitations / deviations from plan
- `init` contains no `strings` field. The UI reads its texts from `app/ui/strings.js` (S3-T2), so they are not sent from Python.
- `conversation` is dispatched only on `new_chat` and carries `id: null` and empty `messages`. Ids and history come with storage (later stage).
- In the GUI integration tests the window is presented, because `requestAnimationFrame` (streamed rendering) does not run for an unmapped window. In the app, a hidden window renders the buffered text at `done`.
- The `api` agent type is answered with an "unsupported" `error` until ApiBackend exists.
