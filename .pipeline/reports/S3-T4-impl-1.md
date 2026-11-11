# Implementation report S3-T4 attempt 1

## Changes
- `app/links.py` (new, no GTK): navigation policy. `decide(uri, index_uri, new_window)` →
  `ALLOW` only for the main page `app/ui/index.html` (fragment ignored, query not allowed),
  `LAUNCH` only for `http`/`https` with a host and `mailto` with an address, `BLOCK` for
  everything else (relative links → `file:…/other.html`, `file:`, `javascript:`, `data:`,
  `about:`, control characters, URIs > 8192 chars). New windows never show a page; a
  new-window request for an external URI is launched like a click. Also the set of context
  menu actions to hide (navigation, downloads, new windows always; `RELOAD` and
  `INSPECT_ELEMENT` unless debug).
- `app/debug.py` (new, no GTK): `debug_enabled()`, `dump_path()`, `build_dump()` (keeps only
  the PLAN §12.1 keys from the page plus `busy`; `visible`, `pinned` (always false until
  pinning exists) and `uri` come from Python), `write_dump()` (atomic replace, mode 0600),
  and the JS for `debug-send` / `debug-click` with the value embedded as an escaped literal
  (`<`, `>`, `&`, U+2028 escaped).
  `debug-send` fills `#prompt` and calls `form.requestSubmit()`, so the page's own `submit()`
  runs with its busy check (note 1 from earlier tasks).
- `app/window.py`: `decide-policy` handler (uses `links.decide`; `RESPONSE` decisions pass),
  `open_external()` → `Gtk.UriLauncher`, or appends the URI to `$AI_PANEL_URI_LOG` instead;
  `context-menu` handler removes the hidden actions and stray separators;
  `javascript_can_open_windows_automatically = False`; `debug_send` / `debug_click`.
- `app/main.py`: `debug-send` (s), `debug-click` (s), `debug-dump` registered only when
  `AI_PANEL_DEBUG=1`; dump written via `bridge.on_dump`. `Adw.StyleManager` color scheme set
  from `chat.theme` (`FORCE_LIGHT`/`FORCE_DARK`/`DEFAULT`); `notify::dark` →
  `controller.refresh_theme()`.
- `app/bridge.py`: `dump` message handled, forwarded only as an answer to a pending
  `request_dump()` (counter capped at 4; unrequested or invalid dumps dropped); `run_script()`
  for app-built scripts.
- `app/controller.py`: `resolve_theme(setting, system_dark)`; `init.theme` is now the
  resolved `light|dark`; `system_dark` callback parameter; `refresh_theme()` re-sends `init`.
- `app/ui/chat.js`: `init` applies `data-theme` on `<html>` (and switches the highlight.js
  light/dark stylesheets) and `--font-size` (clamped 6–72); `request_dump` → `post({type:
  'dump', state})` with screen, agent, badge (`acp`→`tools`, `api`→`chat`), messages
  (`role`, `text` without the copy-button bar, `html`, `thinking: ''`, `tools: []`, `kind`
  for errors), `permission_dialog`, `banner`, effective `theme`, `busy`.
- `app/ui/style.css`: `font-size: var(--font-size, 14px)`; dark/light variables follow
  `data-theme`, `prefers-color-scheme` only when it is absent.
- `app/cli.py`, `app/strings.py`: `ui-dump` calls `org.gtk.Actions.Activate debug-dump` over
  the session bus (`NO_AUTO_START`), waits up to 5 s for a new dump file (inode/mtime/size
  change, valid JSON) and prints it; exit 1 with a hint otherwise.
- `tests/fakes/fake_acp_agent.py`: the `md:` reply also contains
  `[przykład](https://example.com/)` (needed by UAT-S3-4).
- Tests: `tests/unit/test_links.py`, `tests/unit/test_debug.py`,
  `tests/unit/test_cli_ui_dump.py`, additions in `tests/unit/test_bridge.py` and
  `tests/unit/test_controller.py`, `tests/integration/test_debug_actions.py` (marker `gui`),
  `tests/ui/theme-dump.spec.mjs`.
- `README.md`: debug actions, `ui-dump`, link policy, theme and font size.

## Problems from previous report
- None: there was no earlier report for S3-T4. The four notes from the prompt are handled:
  (1) `debug-send` goes through `requestSubmit` → `submit()` (busy check, tested in
  `test_debug_send_respects_the_busy_check`); (2) relative links carry `data-external` but are
  blocked by `links.decide` (they resolve to `file:` URIs other than `index.html`), tested in
  unit and GUI tests; (3) action presence is checked with `gdbus … org.gtk.Actions.List`;
  (4) tests use `AI_PANEL_URI_LOG`, no browser is started.

## How to verify
- `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml make run-headless && source .run/headless.env`
  `gapplication action pl.local.AiPanel debug-send "'md: tabela'"; sleep 2; make -s cli ARGS="ui-dump"`
  → last message `role: assistant`, `html` contains `<table` and `class="hljs`.
- `gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.List`
  → contains `debug-send`, `debug-click`, `debug-dump`; without `AI_PANEL_DEBUG` it does not
  (`test_no_debug_actions_without_ai_panel_debug`).
- With `AI_PANEL_URI_LOG=$PWD/.run/uri.log` at start: `debug-send "'md: link'"`,
  `debug-click "'a[data-external]'"` → `.run/uri.log` is `https://example.com/`, `ui-dump`
  `uri` stays `file://…/app/ui/index.html`.
- `AI_PANEL_DEFAULT_AGENT=fake-slow`: `debug-send "'długo'"`, `sleep 1`,
  `debug-click "'#stop'"`, `sleep 2`, `ui-dump` → last message ends with `Przerwano`.
- `make stop`. All of the above were run by hand and passed.

## Command results
- build: ok, lint: ok, test: ok (`make test` exit 0; pytest 697/697, gjs 1/1, Playwright 66/66
  on Chromium: Playwright WebKit cannot start on this machine, `libevent-2.1.so.7` missing,
  and `make test-ui` falls back with its warning).

## Known limitations / deviations from plan
- Under `make run-headless` with `chat.theme = "system"` the dump says `dark`: the portal on
  the private bus reports `color-scheme = 1` (prefer dark) from the user's settings. This is
  the correct result for `system`. The GUI test uses an explicit `light`/`dark` config.
- Live switching on a desktop theme change (`notify::dark` → `init` again) is covered by a
  controller unit test and a Playwright test of a second `init`. It is not tested end to end,
  because the headless setup cannot switch the desktop scheme.
- `debug-dump.json` also contains `busy` and `uri` (beyond PLAN §12.1); tests use them to wait
  for the end of a turn and to check that the panel did not navigate. `thinking`, `tools`,
  `permission_dialog` and `banner` hold placeholder values until S4.
- `debug-send` while a turn runs does nothing; it does not queue the prompt (same as Enter).
