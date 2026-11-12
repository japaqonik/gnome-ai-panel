# Implementation report S4-T2 attempt 2
## Changes
- app/ui/permission.js: pointer guard on the option buttons. Each time a request is shown
  (first or next from the queue) the buttons get `aria-disabled="true"` and clicks with
  `event.detail > 0` are ignored for 400 ms (`POINTER_GUARD_MS`); clicks with
  `event.detail > 1` (the 2nd/3rd click of a double/triple click) are always ignored.
  Keyboard activation and programmatic `click()` (`detail === 0`, used by `debug-click`) are
  not delayed. `aria-disabled` instead of `disabled` keeps focus on the reject button and
  Enter/Space working. The timer is cleared when the dialog closes or the next request shows.
- app/controller.py: `permission()` logs at debug level when an answer is dropped because
  there is no backend (tester's suggestion).
- tests/ui/permission.spec.mjs: new test: a mouse click right after the request is ignored
  and the button is `aria-disabled`; Enter answers at once; the next request is guarded
  again; after the guard ends a real click answers.
- README.md: documents the 0.4 s click guard, immediate keyboard, and that the stop button
  is unreachable while the dialog is open (answer or Esc first).

## Problems from previous report
- Double click on "Zezwól" also allowed the queued request → fixed by the guard above;
  `tests/ui/permission-edge.spec.mjs` "double click" now passes (unchanged).
- Suggestion: stop button unreachable behind the modal → documented in README (no stop
  button inside the dialog; Esc rejects and the agent decides how to continue).
- Suggestion: silent drop without backend → debug log added.

## How to verify
- `PW_BROWSER=chromium npx playwright test tests/ui/permission.spec.mjs tests/ui/permission-edge.spec.mjs` → 23 passed.
- Headless flow from README (`fake-perm`, `debug-send`, `debug-click`) unchanged, since
  `debug-click` uses `node.click()` (detail 0).

## Command results
- build: ok, lint: ok, test (`PW_BROWSER=chromium make test`): pytest 754/754, GJS 1/1,
  Playwright 104/104 (includes the tester's edge spec).

## Known limitations / deviations from plan
- A deliberate single mouse click within 400 ms of a request appearing is ignored; the user
  clicks again. WebKit not run locally (libraries missing), Chromium used.
