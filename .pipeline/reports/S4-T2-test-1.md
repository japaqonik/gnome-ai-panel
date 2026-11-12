# Test report S4-T2 attempt 1
Verdict: FAIL
## Command results
- build: exit 0
- lint: exit 0 (ruff, ruff format, eslint; schema check skipped, no extension/schemas yet)
- test (`PW_BROWSER=chromium make test`): exit 0. pytest 754/754, GJS 1/1, Playwright 95/95.
  WebKit cannot launch on this machine (libevent missing), so Chromium was used.
- New tester spec `tests/ui/permission-edge.spec.mjs`: 7/8 passed, 1 failed (problem 1 below).

## Done-when criteria
- [x] `npx playwright test tests/ui/permission.spec.mjs` → passed. Evidence: 14/14 on Chromium
  inside `make test`.
- [x] headless + `fake-perm`, `debug-send "'zrób'"` → `ui-dump`: `permission_dialog {open: true,
  title: "Zapis pliku out.txt"}`, tool `pending`, busy. `debug-click "'[data-option-kind=allow_once]'"`
  → tool `call_perm` `completed`, reply "Zezwolono", dialog closed.
- [x] after `new-chat`, the same steps with `reject_once` → tool `failed`, reply "Odmowa" (the
  agent's refusal text).
- Extra check: with the dialog open, a programmatic click on `#stop` closed the dialog; the tool
  ended `failed`, the reply "Przerwano", and the log shows no answer from the controller (the
  backend answered `cancelled`).

## Listed tests (reviewed)
- Playwright: modal + focus on reject, Esc → `reject_once`, Esc without reject_once → `null`,
  two requests one after another, done/error/conversation/stop close without answering, XSS as
  text, long command in full, Tab trap. Behavioural and meaningful.
- Integration controller + AcpBackend (`tests/integration/test_controller_permissions_acp.py`):
  allow/deny/null checked against what the fake agent recorded; cancel and new_chat with an open
  request → agent receives `{"outcome": "cancelled"}`. Good.
- Unit controller and bridge tests cover unknown option → reject, single answer, late answers.
- The replaced S3 test (`…rejected_until_dialog_exists`) asserted behaviour this task removes;
  replacing it is justified, not a weakening.

## Tests added
- tests/ui/permission-edge.spec.mjs (8 cases): Enter right after opening rejects and does not
  re-send the prompt; Esc with focus on the input block rejects; typing while open does not reach
  the prompt; a second Esc posts nothing more; a request after `done` is not shown; a later request
  of the same turn opens with focus on reject; empty option list → fallback, Esc → `null`;
  **double click on allow must not allow the queued request (fails)**.

## Problems (for the implementer; each actionable)
1. A double click on an allow button also allows the next queued request, which the user never
   saw. Reproduce: `PW_BROWSER=chromium npx playwright test tests/ui/permission-edge.spec.mjs -g
   "double click"`. Two requests are queued (`perm-1`, `perm-2`), and the user double-clicks
   "Zezwól" on `perm-1`. Expected: only `perm-1` is answered, and `perm-2` stays on screen until the
   user acts on it. Actual: the page posts `{request_id: "perm-2", option_id: "allow"}` too. Cause:
   in `app/ui/permission.js`, `answer()` calls `showNext()` synchronously. The new buttons are in the
   same order at the same position, so the second click of the double click lands on the new
   "allow" button. This breaks the "nothing is allowed without the user" rule (FR-11). Possible
   fixes: ignore option clicks for a short time (e.g. 300–500 ms) after a request is shown, ignore
   clicks with `event.detail > 1`, or both. Keyboard activation must stay immediate. The new test
   must pass, and the existing tests must keep passing.

## Suggestions (non-blocking)
- While the dialog is open, `#app` is inert, so a real user cannot press the stop button; only Esc
  (reject) or an answer closes the dialog. This is acceptable for a modal. A note in the README, or a
  "stop" action inside the dialog, could make it clearer.
- `ChatController.permission` pops the request before checking `backend is None`. In that case
  the answer is lost silently. This is harmless because the backend answers `cancelled` at turn end,
  but a debug log line would help.
