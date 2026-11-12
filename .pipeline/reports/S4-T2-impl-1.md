# Implementation report S4-T2 attempt 1
## Changes
- app/controller.py: a `PermissionRequest` is no longer rejected at once. It is stored in the
  turn (`_Turn.permissions`: request id → offered option ids) and dispatched as
  `permission_request {request_id, tool_call_id, title, kind, raw_input, options: [{id, name, kind}]}`.
  New `ChatController.permission(request_id, option_id)` → `backend.respond_permission`. It
  answers only open requests of the running turn, each at most once. An option the agent did not
  offer becomes `None` (rejection). Answers without a turn, for unknown ids or after the turn ended are
  dropped with a warning that names no option values. `_finish` clears the open requests. The backend answers them
  itself (ACP `_cancel_permissions` → `outcome: cancelled`), so cancel and `new_chat` need no extra code.
- app/bridge.py: `permission` moved out of `LATER_TYPES`. `_handle_permission` checks
  `request_id` (non-empty string ≤ 256) and `option_id` (missing/null or the same), drops invalid
  messages with a warning, and calls `handler.permission`. `MessageHandler` gained `permission`.
- app/ui/permission.js (new): the dialog module. It keeps a queue and shows one request at a time in
  `#permission-dialog` (`role="dialog"`, `aria-modal="true"`, labelled by the heading). The title,
  kind (Polish label for ACP kinds) and the full input go in via `textContent`. The input is a
  wrapping, scrollable `<pre>`, so it is never cut. There is one button per agent option, labelled with
  the agent's `name` (fallback: a label by kind, then the id) and carrying `data-option-id` and
  `data-option-kind`. Allow buttons are primary. The focus goes to `reject_once`, or else to another `reject_*`
  option, or else to an added "Odrzuć" button that answers `null`. Esc posts the `reject_once` id or `null`
  (never `reject_always`). Tab and Shift+Tab stay inside the dialog, `#app` is `inert` while it is open, and the focus
  returns to the prompt when it closes. `closeAll()` closes it without posting. `state()` feeds the dump.
- app/ui/chat.js: wires the dialog. `permission_request` is accepted only while busy. `done`,
  `error`, `conversation` and the stop button call `closeAll()`. The dump field `permission_dialog` is
  now `{open, title}` from the dialog.
- app/ui/render.js: `formatInput` moved here from chat.js so that the tool cards and the dialog share it.
- app/ui/index.html: dialog markup and the `permission.js` script. app/ui/strings.js: dialog texts and tool
  kind labels. app/ui/style.css: overlay and dialog styles.
- tests/fakes/fake_acp_agent.py: `--record` also writes `{"method": "session/request_permission",
  "result"}`, so the tests can check what the agent actually received.
- Tests:
  - tests/ui/permission.spec.mjs (new, 14): the modal with focus on reject, inert background and the dump;
    click → `permission`; Esc → `reject_once`; Esc without `reject_once` → `null`; the fallback reject button;
    two requests → the second after the first, with a repeated id ignored; `done`/`error`/`conversation`/stop
    close without answering; XSS as text; a long command in full; Tab trap; invalid requests and requests outside a turn.
  - tests/unit/test_controller_permissions.py (new, 8): dispatched fields, no automatic answer,
    allow, null, unknown option → reject, single answer, unknown, late and new-chat answers dropped.
  - tests/integration/test_controller_permissions_acp.py (new, 5): controller + AcpBackend +
    fake agent. Allow → `completed` + "Zezwolono"; reject → `failed` + "Odmowa"; null → the agent's reject option;
    cancel and new_chat with an open request → the agent receives `outcome: cancelled`.
  - tests/integration/test_debug_actions.py: 2 GUI tests (UAT-S4-1 flow with allow then reject;
    new-chat closes the dialog). tests/unit/test_bridge.py: permission routing and validation.
  - tests/unit/test_controller.py: `test_permission_request_is_rejected_until_dialog_exists`
    replaced by `…_is_dispatched_and_not_answered_automatically`. The old test asserted the S3
    placeholder behaviour that this task removes. In test_bridge.py, the "unhandled type" parametrisation uses
    `select_agent` instead of `permission`.
- README.md: the status paragraph (stage S4, the dialog), the dump field, a fake-perm walkthrough, and the UI and controller descriptions.

## Problems from previous report
- No previous S4-T2 report. The S4-T1 test report listed no problems.

## How to verify
- `PW_BROWSER=chromium npx playwright test tests/ui/permission.spec.mjs` → 14 passed. Plain
  `npx playwright test …` uses WebKit, which cannot start here because `libevent-2.1.so.7` is missing (an environment issue, same as S4-T1).
- `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-perm make run-headless && source .run/headless.env`.
  `debug-send "'zrób'"` → `ui-dump` shows `permission_dialog == {open: true, title: "Zapis pliku out.txt"}`.
  `debug-click "'[data-option-kind=allow_once]'"` → `tools[0].status == "completed"`, text "Zezwolono".
  After `new-chat`, the same steps with `reject_once` → `failed`, text "Odmowa". Checked manually, then `make stop`.

## Command results
- build: ok, lint: ok, test: pytest 754/754, gjs 1/1, Playwright 95/95 (Chromium fallback)

## Known limitations / deviations from plan
- The dialog only lives in the page. Python does not re-send open requests after a page reload
  (a reload is debug-only). Such a request stays open until the turn ends or is cancelled.
- When a turn is cancelled, the page closes the dialog right away. The backend answers the agent
  `cancelled` once `session/cancel` is processed.
- Answers for requests that are no longer open are dropped in the controller. The page cannot
  answer twice, because the dialog moves to the next request at once.
