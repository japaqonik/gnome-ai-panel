# Test report S3-T4 attempt 1
Verdict: PASS

## Command results
- build: `make build` exit 0
- lint: `make lint` exit 0 (also after the tester's new test files)
- test: `make test` exit 0. Before tester additions: pytest 697/697, gjs 1/1, Playwright 66/66.
  After: pytest 720/720, gjs 1/1, Playwright 66/66. Playwright ran on Chromium: WebKit
  MiniBrowser fails with `libevent-2.1.so.7: cannot open shared object file`, and
  `make test-ui` prints the documented fallback warning.
- No new browser process appeared during `make test` (pgrep of firefox/chrome/epiphany
  before and after: identical PID sets). No `python -m app`, Xvfb, fake agent processes or
  `/tmp/ai-panel-runtime.*` directories remained after the tests and after `make stop`.

## Done-when criteria
- [x] Headless `debug-send 'md: tabela'` then `ui-dump` shows an assistant message whose `html`
  contains `<table`. Evidence: `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml make run-headless`,
  `gapplication action pl.local.AiPanel debug-send "'md: tabela'"`, `sleep 2`,
  `make -s cli ARGS="ui-dump"` → exit 0, `messages[-1].role == "assistant"`, `<table` and
  `class="hljs` present. `agent: fake-echo`, `badge: tools`, `uri: file://…/app/ui/index.html`.
- [x] Without `AI_PANEL_DEBUG` the action `debug-send` does not exist (agreed deviation:
  `gdbus … org.gtk.Actions.List`). Evidence: the app started under `xvfb-run dbus-run-session`
  with isolated XDG dirs and `AI_PANEL_DEBUG` unset → `(['new-chat', 'toggle', 'hide', 'show',
  'quit', 'visible'],)`; `gapplication action … debug-send` → `Unknown action 'debug-send'`,
  exit 1; `python -m app.cli ui-dump` → exit 1 with a hint. With `make run-headless` the
  list contains `debug-send`, `debug-click`, `debug-dump`.
- [x] `make test` → exit 0 (see above).
- Tests listed in the task exist and pass: full turn through `debug-send`/`debug-dump`,
  external link click keeps the WebView URI and writes to `AI_PANEL_URI_LOG`,
  `chat.theme = "dark"` → dump `theme == "dark"` (tests/integration/test_debug_actions.py).

## UAT S3 (checked by hand, headless, fake config)
- UAT-S3-1: `md: tabela` → `<table` and `class="hljs`, role assistant. OK.
- UAT-S3-3 (`fake-slow`): `debug-send 'długo'`, dump `busy: true`; a second `debug-send`
  during the turn was ignored; `debug-click '#stop'` → last message ends with `Przerwano`,
  `busy: false`. OK.
- UAT-S3-4 (`AI_PANEL_URI_LOG=$PWD/.run/uri.log`): `debug-send 'md: link'`,
  `debug-click 'a[data-external]'` → uri.log contains `https://example.com/`, dump `uri` still
  `index.html`. OK.
- UAT-S3-5: `AI_PANEL_CONFIG=/nonexistent` → `"screen": "empty"`. OK.
- Dump file `.run/home/state/gnome-ai-panel/debug-dump.json` has mode 0600.
- `debug-send` with `</script><b>x\u2028`, empty string and `debug-click '#nonexistent'`
  did not break the page or the app.

## Tests added
- tests/unit/test_links_edge.py: look-alike index URIs (`file://localhost/…`, `./`, `../`,
  different case) blocked; malformed `http://[::1`, `mailto:?subject=x`, tabs inside the URI,
  `blob:`, `ws:`, `intent:` blocked (also as new-window requests); uppercase schemes,
  userinfo, IDN host launched; URI exactly at `MAX_URI_LENGTH` accepted, one char more refused.
- tests/integration/test_debug_actions_edge.py (marker `gui`): `AI_PANEL_DEBUG` = `0`,
  `true`, `yes`, empty → no debug actions; `file:///etc/passwd` link blocked and `mailto:`
  launched (to the URI log); `target="_blank"` link → exactly one launch, no navigation, app
  alive; `debug-send` with quotes, backslash, `</script>`, `<!--`, U+2028, `${x}`, backticks
  and a newline arrives verbatim as the user message.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
1. `links.is_external(" https://example.com/")` returns True because `urlsplit` strips leading
   whitespace, and the untrimmed string would go to `Gtk.UriLauncher`. WebKit normalises
   request URIs, so this is not reachable from the page today; stripping or rejecting
   surrounding whitespace in `is_external` would make the function safe on its own.
2. The live desktop theme switch is covered only by unit and Playwright tests (documented
   limitation).
