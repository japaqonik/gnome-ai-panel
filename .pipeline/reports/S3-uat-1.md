# UAT report S3 attempt 1
Verdict: PASS

Environment: Ubuntu 26.04, working tree on top of fa15568 (S3 changes uncommitted; `app/ui/vendor/`
untracked, to be committed). `make setup` 0, `make build` 0, `make lint` 0, `make test` 0
(pytest 720 passed, GJS 1 passed, Playwright 66 passed on Chromium via the documented WebKit
fallback). Logs: `.pipeline/uat-scripts/s3-{setup,build,lint,test}.log`. All GUI checks used
`make run-headless` (isolated HOME/XDG, private bus); CLI checks used a temp HOME/XDG
(`.pipeline/uat-scripts/s2env.sh`); exact exit codes taken from `.venv/bin/python -m app.cli`.

## Criteria
- UAT-S3-1: PASS. `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml make run-headless` (rc 0, `ui ready`),
  `debug-send "'md: pokaż'"`, `sleep 2`, `make -s cli ARGS="ui-dump"` (rc 0, pure JSON). Dump: 2 messages
  `[user, assistant]`; `messages[-1].role == "assistant"`; `html` contains `<table>` (header + 2 rows),
  `<code class="language-python hljs">` with `hljs-built_in`/`hljs-string` spans, a "Kopiuj" button with
  `aria-label="Kopiuj kod"`, and a link with `rel="noopener noreferrer" data-external`. `screen: chat`,
  `agent: fake-echo`, `busy: false`, `uri` is still `file://…/app/ui/index.html`.
- UAT-S3-2: PASS. `PW_BROWSER=chromium npx playwright test tests/ui/render.spec.mjs -g XSS` → 1 passed.
  The full render + chat specs pass (34 passed). `grep -rE "https?://" app/ui/index.html app/ui/*.js` → rc 1.
- UAT-S3-3: PASS. With `AI_PANEL_DEFAULT_AGENT=fake-slow`: `debug-send "'długo'"`, after 1 s the dump shows
  `busy: true, agent: fake-slow`; `debug-click "'#stop'"`, after 2 s the last assistant message text is
  `fragment 1 … fragment 6 \nPrzerwano`, `busy: false`. A second stop-and-cancel turn ("po stopie") also ends
  with "Przerwano". A `debug-send` issued during the running turn was not added (no extra user message).
- UAT-S3-4: PASS. `AI_PANEL_URI_LOG=$PWD/.run/uri.log` + `run-headless`, `debug-send "'md: link'"`,
  `debug-click "'a[data-external]'"`: `.run/uri.log` contains `https://example.com/`; the dump `uri` is
  unchanged (`file://…/index.html`), screen still `chat` with both messages; app log:
  `link logged to AI_PANEL_URI_LOG instead of launching`. No browser opened.
- UAT-S3-5: PASS. `AI_PANEL_CONFIG=/nonexistent make run-headless` → dump `"screen": "empty"`, `agent: null`,
  `messages: []`. A `debug-send "'hej'"` on that screen adds nothing.

Additional user-style checks (all PASS):
- Plain prompt `Cześć` → `Echo: Cześć`; empty prompt `''` is not sent.
- `new-chat` clears the list (0 messages); the next prompt starts a fresh conversation (`Echo: po nowym`).
- `show` → `visible` = true.
- `make stop` after a fake-slow turn leaves no `fake_acp_agent.py` process.
- Temp config with `chat.theme = "light"` → dump `theme: light`; `"dark"` → `dark`. The same config had an
  invalid agent `bad` (no command); the valid agent still works (`Echo: test`), log `1 agent(s), 2 error(s)`.
- Without `AI_PANEL_DEBUG` (own `xvfb-run dbus-run-session`, script `.pipeline/uat-scripts/s3-nodebug.sh`):
  `org.gtk.Actions.List` → `['new-chat', 'toggle', 'hide', 'show', 'quit', 'visible']`;
  `debug-send` → `Unknown action ‘debug-send’`; `quit` → exit 0.
- `make vendor` → rc 0, no diff in `app/ui/vendor` against the files present.

## Regression (earlier stages)
- UAT-S1-1: PASS (setup/lint/test all 0, see above).
- UAT-S1-2: PASS. `toggle` → `[<true>]`, `toggle` → `[<false>]`; `grep -c "ui ready"` → 27. A second
  `python -m app` exits 0.
- UAT-S1-3: PASS. `make stop` rc 0 (app, dbus-daemon, Xvfb stopped), no `python -m app` left, second
  `make stop` rc 0, no `/tmp/ai-panel-runtime.*` left.
- UAT-S1-4 [manual]: needs human check.
- UAT-S2-1: PASS. `chat fake-echo 'Cześć' --json`: 4 JSON lines, 3 `text_delta`, last
  `{"type": "done", "stop_reason": "end_turn"}`, rc 0.
- UAT-S2-2: PASS. fake-missing / fake-badver / fake-auth → rc 2 each, three different Polish messages
  (missing command, protocol 99 vs 1, login required with "Fake login"), no traceback.
- UAT-S2-3: PASS. `check-config` on `config_invalid.toml` → `agents.broken.command: wymagane` + 3 more, rc 1;
  `agents --json` lists only `good`.
- UAT-S2-4: PASS. `chat fake-env SECRET_VAR` → `s3cr3t-value`, rc 0; `grep -r s3cr3t-value $XDG_STATE_HOME/gnome-ai-panel/` → rc 1.
- UAT-S2-5 [manual]: PASS (run by tester). Temp config (`command="kiro-cli"`, `args=["acp"]`, `cwd` in a temp
  dir), real HOME for the Kiro login, temp `XDG_STATE_HOME`: `test-agent kiro` → `Kiro CLI Agent 2.26.0`,
  `protokół: 1`, OK, rc 0; `chat kiro 'Powiedz OK'` → `OK`, rc 0. No `kiro-cli acp` process left.
- Other: `test-agent fake-echo` rc 0; `AI_PANEL_CONFIG=/nonexistent agents --json` → `[]` rc 0;
  `secret set test-x` inside `dbus-run-session` with temp HOME/XDG_RUNTIME_DIR → `błąd: brak usługi Secret Service …`, rc 1
  (real keyring not touched).

## Problems (for the implementer; each actionable)
None.

## Observations (non-blocking)
1. In the dump the "Przerwano" marker appears in `messages[-1].text` but not in `messages[-1].html`
   (it is a separate element outside the rendered markdown). The criterion asks only that the last message
   contains it, which holds.
2. With `chat.theme = "system"` the headless run reports `theme: dark`: inside the isolated session
   `gsettings get org.gnome.desktop.interface color-scheme` returns `'prefer-dark'` (the distro default,
   since `.run/home` has no dconf database), so the app follows it correctly. Following a live desktop
   change could not be observed headless.
3. `chat.font_size` is not part of the dump, so it was not checked from the outside (covered by tests).
4. `make` without `-s` prints the script name (`scripts/run-headless.sh`, `scripts/stop.sh`) on stdout.
   This is cosmetic.
5. `app/ui/vendor/`, `render.js`, `chat.js`, `strings.js` are untracked until the S3 commit. The git stage
   must add them.

## Needs human check
- UAT-S1-4: on the real GNOME session, `make run && gapplication action pl.local.AiPanel show`, check the
  window has no title bar and shows „Dodaj agenta”, then `make stop`.
- Visual S3 check (optional, not a separate criterion): on the real desktop with a configured agent, type a
  prompt and look at the markdown/table/code highlighting, the copy button, font size and the light/dark switch
  when the desktop theme changes.

Cleanup: all started processes were stopped (no `python -m app`, Xvfb, fake agents or `kiro-cli acp`
left); temporary `/tmp/aip-uat-s3.*`, dump copies and `.run/uri.log` were removed.
