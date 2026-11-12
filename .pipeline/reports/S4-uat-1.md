# UAT report S4 attempt 1
Verdict: PASS

Environment: Ubuntu 26.04, working tree on top of 95e13a4 (S4 changes uncommitted, new files such as
`app/ui/permission.js` and the S4 tests untracked). `make setup` 0, `make build` 0, `make lint` 0,
`PW_BROWSER=chromium make test` 0 (pytest 846 passed, GJS 1 passed, Playwright 136 passed). Plain
`make test-ui` without `PW_BROWSER` also exits 0 and prints the documented WebKit → Chromium fallback warning.
Logs: `.pipeline/uat-scripts/s4-{setup,build,lint,test}.log`. All GUI checks used `make run-headless`
(isolated HOME/XDG, private bus) and ended with `make stop`. CLI checks used a temp HOME/XDG
(`.pipeline/uat-scripts/s2env.sh`). Helpers: `.pipeline/uat-scripts/s4-lib.sh`.

## Criteria
- UAT-S4-1: PASS. `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-perm make run-headless`
  (rc 0). `debug-send "'zrób'"`, 1 s → dump `permission_dialog = {open: true, title: "Zapis pliku out.txt"}`,
  `busy: true`, tool `call_perm` `pending`. `debug-click "'[data-option-kind=allow_once]'"`, 1 s → dialog closed,
  `tools[0].status == "completed"`, reply `Zezwolono`. `new-chat` → 0 messages. Repeated with `reject_once` →
  `tools[0].status == "failed"`, reply `Odmowa`, dialog closed.
  Extra: with a dialog open, `new-chat` closed it and cleared the list, and the next request worked (allow → `completed`).
- UAT-S4-2: PASS. `AI_PANEL_DEFAULT_AGENT=fake-tool`, `debug-send "'x'"` → `messages[-1].thinking == "Sprawdzę plik."`,
  `tools == [{id: call_1, title: "Odczyt pliku notes.txt", status: completed}]`, text `Plik zawiera: zawartość.`.
  Collapsed-by-default is not exposed in the dump (the thinking block is outside `html`). It is covered by
  `tests/ui/tools.spec.mjs` (passed).
- UAT-S4-3: PASS (after removing the leftover marker, see Observation 1). `AI_PANEL_DEFAULT_AGENT=fake-crash-once`,
  `debug-send 'a'`, `debug-send 'b'` → messages: `user a`; `error crashed` "Agent przestał działać / Proces agenta
  zakończył działanie (kod 3). / Ostatnie linie stderr agenta: boom / Następna wiadomość uruchomi agenta ponownie…";
  `user b`; `notice context_lost` "Agent został uruchomiony ponownie, poprzedni kontekst utracony";
  `assistant` "Echo: b".
- UAT-S4-4: PASS. `config_fake.toml`: `Describe agent` → `'fake-echo'`; `agent "'fake-models'"` → `Describe agent`
  `'fake-models'`, dump `agent: fake-models, badge: tools`; `Describe agents` → `a(ss)` list of all 16 fake agents
  (`('fake-echo', 'fake-echo'), …`). `debug-send 'a'` → `[fake-small] Echo: a`. An unknown id (`'nope'`) is ignored.
  `SetState agent <'fake-echo'>` switches and clears the conversation. `SetState agents` / `SetState visible`
  do not change the read-only states. With `config_valid.toml`: `moj-agent` → badge `tools`, `szybki-czat` (api) →
  badge `chat`. A prompt to it gives the error card "Agent „szybki-czat” typu „api” nie jest jeszcze obsługiwany.",
  as the README documents.

Additional S4 checks (all PASS, matching README):
- Error cards in the panel: `fake-missing` → `spawn` "Nie można uruchomić agenta / Nie znaleziono polecenia:
  /nonexistent/agent" + hint; `fake-badver` → `protocol` "Niezgodny protokół agenta … 99 (obsługiwana: 1)";
  `fake-auth` → `auth` "Agent wymaga zalogowania", method "Fake login: Run `fake-agent login` in a terminal" and the
  hint to log in in a terminal.
- Restart limit: `fake-crash`, 5 prompts → 4 `crashed` cards (3 with `context_lost` notices), the 5th card says
  "Agent ulegał awarii zbyt często (3 ponowne uruchomienia w ciągu 60 s)" with a "Nowa rozmowa" button
  (`data-action=new-chat`). A 6th prompt is not sent. Clicking the button clears the list and enables the prompt.
  Within the same 60 s a prompt still gets the limit error, as documented. Switching to `fake-echo` works.
- Cancel (temp config with the `slow-tool`, `stubborn` and `slow` scenarios): `slow-tool` tool `in_progress` →
  0.3 s after `#stop` the card is `cancelled` and the reply ends with `Przerwano`, `busy: false`. `stubborn`: 2 s after
  stop the turn is still busy, at 6 s it ends with `Przerwano`. The next prompt shows the notice "Agent nie potwierdził
  przerwania poprzedniej odpowiedzi, więc rozpoczęto nową sesję; poprzedni konte…".

## Regression (earlier stages)
- UAT-S1-1: PASS (setup/lint/test all 0, see above).
- UAT-S1-2: PASS. `toggle` → `[<true>]`, `toggle` → `[<false>]`, `grep -c "ui ready"` → 51, second `python -m app` → 0.
- UAT-S1-3: PASS. `make stop` 0, no `python -m app` left, second `make stop` 0, no `/tmp/ai-panel-runtime.*`.
- UAT-S1-4 [manual]: needs human check.
- UAT-S2-1: PASS. `chat fake-echo 'Cześć' --json` → 4 JSON lines, 3 `text_delta`, last `{"type": "done", "stop_reason": "end_turn"}`, rc 0.
- UAT-S2-2: PASS. fake-missing / fake-badver / fake-auth → rc 2 each, three different Polish messages, no traceback.
- UAT-S2-3: PASS. `check-config config_invalid.toml` → `agents.broken.command: wymagane` + 3 more, rc 1; `agents --json` lists only `good`.
- UAT-S2-4: PASS. `chat fake-env SECRET_VAR` → `s3cr3t-value`, rc 0; `grep -r s3cr3t-value $XDG_STATE_HOME/gnome-ai-panel/` → 1.
- UAT-S2-5 [manual]: not re-run (real `kiro-cli` login). It needs a human check. The S3 UAT tester confirmed it.
- UAT-S3-1: PASS. `md: pokaż` → last message `assistant`, `html` contains `<table` and `hljs`.
- UAT-S3-2: PASS. `PW_BROWSER=chromium npx playwright test tests/ui/render.spec.mjs -g XSS` → 1 passed (also 30/30 and
  100/100 with `--repeat-each`). See Observation 3 for a failure the tester caused.
- UAT-S3-3: PASS. `fake-slow`, stop after 1 s → `… fragment 5 \nPrzerwano`, `busy: false`.
- UAT-S3-4: PASS. `.run/uri.log` → `https://example.com/`, WebView `uri` unchanged.
- UAT-S3-5: PASS. `AI_PANEL_CONFIG=/nonexistent` → `screen: empty`, `agent: null`, `badge: null`.

## Problems (for the implementer; each actionable)
None.

## Observations (non-blocking)
1. The `fake-crash-once` marker persists in `.run/home/.cache/gnome-ai-panel-fake/crash-once/.fake-acp-crash-once`
   between `make run-headless` runs. On this machine it was already there, so the literal UAT-S4-3 steps showed
   `Echo: a` / `Echo: b` with no crash. The README documents this ("delete it to make the agent crash again"). Adding
   `rm -f .run/home/.cache/gnome-ai-panel-fake/crash-once/.fake-acp-crash-once` to the README "Try it" block (or
   the UAT step) would make it reproducible.
2. While the window is hidden (headless default, `visible: false`), streamed `text_delta`s are not rendered,
   because rendering waits for `requestAnimationFrame`. Mid-turn dumps show empty text, and the text appears at
   `done`/stop or when the window is shown (`show` → fragments visible mid-turn). For a real user the window is
   visible, so this does not affect them, but a mid-turn `ui-dump` of a hidden window is misleading.
3. Tester's own mistake: running `npx playwright` in a shell that still had `.run/headless.env` sourced fails with
   "Executable doesn't exist at .run/home/cache/ms-playwright/…", because the env file redirects `HOME`/`XDG_CACHE_HOME`.
   The README already says to source it in the shell or a subshell used for actions. A one-line hint
   ("run tests in a different shell") would help.
4. `debug-click "'#stop'"` while the permission dialog is open does stop the turn and close the dialog.
   `element.click()` bypasses `inert`, so this is a debug-tool path, not user input. Real pointer and keyboard
   blocking under the modal is covered by `permission.spec.mjs`, and on the desktop it needs the human check below.
5. The model selector cannot be operated through debug actions (`debug-click` cannot change a `<select>`) and the
   dump has no `model` field. The model switch was verified only through `tests/ui/header.spec.mjs` and
   `tests/integration/test_controller_models_acp.py` (both passed).
6. New S4 files (`app/ui/permission.js`, many tests) are untracked. The git stage must add them.

## Needs human check
- UAT-S1-4: on the real GNOME session, `make run && gapplication action pl.local.AiPanel show`. Check that the window
  has no title bar and shows „Dodaj agenta”, then run `make stop`.
- UAT-S2-5: `test-agent kiro` / `chat kiro 'Powiedz OK'` with a logged-in `kiro-cli`.
- Visual S4 check on the real desktop (optional, no separate criterion):
  - the "Myśli…"/"Myślenie" block is collapsed;
  - tool card status icons, "Wejście"/"Wynik";
  - the permission dialog: focus on reject, Esc rejects, the 0.4 s click guard, the stop button not usable under the modal;
  - the amber/green mode badge;
  - the model list with `fake-models` after the first prompt and changing the model.

Cleanup: all started processes stopped (no app, Xvfb, dbus-daemon or fake agents left), no `/tmp/ai-panel-runtime.*`.
Temp configs (`/tmp/aip-uat-s4.*`), temp HOMEs and logs in `/tmp` were removed.
