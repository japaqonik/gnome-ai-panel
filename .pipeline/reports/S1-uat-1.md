# UAT report S1 attempt 1
Verdict: PASS

Date: 2026-11-11, host Ubuntu 26.04, GNOME Shell 50.1 (Wayland). Start state: no `.run/*.pid`
files and no `python -m app`, Xvfb or private dbus-daemon processes; `make stop` → exit 0.

## Criteria
- UAT-S1-1: PASS. Ran `make setup; make lint; make test` with exit codes recorded
  (full logs in `.pipeline/uat-scripts/{setup,lint,test}.log`). Exit codes: setup=0, lint=0, test=0.
  Lint: ruff "All checks passed!", "19 files already formatted", ESLint with no output.
  Test: pytest `86 passed, 9 warnings`, GJS `1 passed`, Playwright `3 passed`.
  Playwright printed `test-ui: Playwright WebKit cannot launch on this machine, falling back to chromium.`
  (missing `libevent-2.1.so.7`), which is the documented behaviour.
- UAT-S1-2: PASS. `make run-headless` → exit 0, stderr `run-headless: ui ready (pid 19813, DISPLAY=:2, …)`,
  `.run/headless.env` created. With `source .run/headless.env`: `Describe visible` before toggle →
  `[<false>]`; `toggle` → `[<true>]`; `toggle` → `[<false>]`.
  `grep -c "ui ready" .run/home/state/gnome-ai-panel/app.log` → `4` (≥ 1; the log also has lines from earlier runs).
- UAT-S1-3: PASS. `make stop` → exit 0, stderr `app stopped (pid 19813)`, `dbus-daemon stopped (pid 19809)`,
  `Xvfb stopped (pid 19801)`. `pgrep -af "python -m app"` → no result, no Xvfb. The pid files,
  `headless.env` and `/tmp/ai-panel-runtime.fvHc0B` were removed. The second `make stop` → exit 0.
- UAT-S1-4 [manual]: PARTIAL, needs human check. On the real GNOME 50.1 Wayland session:
  `make run` → exit 0 (`run: ui ready (pid 20342 …)`); `gapplication action pl.local.AiPanel show` → exit 0;
  `Describe visible` → `[<true>]`; `make stop` → exit 0, process gone. I could not look at the
  window, so the "no title bar" and "Dodaj agenta" parts were not checked by eye. Indirect evidence:
  the Playwright smoke test sees `#empty-state`, and the string "Dodaj agenta" is in `app/ui/index.html`.

## Exploratory checks (headless instance)
- `show` twice → `true` both times; `hide` twice → `false` both times; `new-chat` → exit 0,
  log `new chat requested`, visibility unchanged.
- Unknown action `bogus` → exit 1, `Unknown action ‘bogus’` (expected).
- A second `python -m app` while the app is running → exit 0, the running window is shown
  (`visible` = `true`); `python -m app --background` → exit 0. Only one main process exists (pid 19813).
- `org.gtk.Actions.List` → `['new-chat', 'toggle', 'hide', 'show', 'quit', 'visible']`.
- Isolation: the real session bus has no `pl.local.AiPanel` owner while the headless instance runs
  (`NameHasOwner` → `false`).
- README extras: `make build` → exit 0 (prints skip messages for the schemas and extension that do not exist yet).
  The README one-liner `xvfb-run -a dbus-run-session -- .venv/bin/python -m app` (with HOME/XDG
  redirected to a temp dir) logged `ui ready` within about 1 s and wrote `state/gnome-ai-panel/app.log`.
- `git status --porcelain` shows no `.venv/` or `node_modules/` entries.

## Regression (earlier stages)
None. S0 contained only the plan commit.

## Problems (for the implementer; each actionable)
None.

## Observations (non-blocking)
- The criterion says "fresh clone", but the S1 files are not committed yet (only S0 is). `make setup`
  was therefore run on the working tree, not on a real `git clone`. Re-check after the S1 commit if desired.
- `make test-py` prints `libEGL warning: DRI3 error: Could not get DRI3 device` under Xvfb. This is harmless.
- `.run/home/state/gnome-ai-panel/app.log` keeps lines across headless runs, so the `grep -c "ui ready"`
  count in UAT-S1-2 includes earlier runs. The check only needs ≥ 1, so the result still holds.
- Playwright ran on Chromium because the WebKit host libraries are missing (`sudo npx playwright install-deps webkit`).
- `gapplication list-actions` was not tested because it needs the S6 .desktop file. `gdbus … org.gtk.Actions.List` was used instead.

## Needs human check
- UAT-S1-4: run `make run && gapplication action pl.local.AiPanel show` on the GNOME session and
  confirm the window has no title bar and shows "Brak skonfigurowanych agentów — Dodaj agenta". Then run `make stop`.
