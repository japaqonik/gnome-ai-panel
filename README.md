# GNOME AI Panel

Side panel for GNOME (Wayland, GNOME Shell 50) with a chat window that talks to any agent
speaking the [Agent Client Protocol](https://agentclientprotocol.com) (e.g. `kiro-cli acp`,
`claude-agent-acp`) or directly to the Anthropic Messages API. The project consists of:

- the application `pl.local.AiPanel` (Python, GTK 4, libadwaita, WebKitGTK) running in the
  background and controlled through D-Bus actions,
- a GNOME Shell extension that docks the window to a screen edge and toggles it with a shortcut.

Status: early development (stage S3). The application reads the configuration at start, shows
the chat page and answers the D-Bus actions below. A prompt typed in the window is sent to the
chosen agent and the reply streams in as markdown; the stop button cancels the turn and the
`new-chat` action starts a new conversation. Links in replies open in the default browser;
the panel itself never navigates away. The page follows `chat.theme` and `chat.font_size`.
Thinking, tool calls and permission dialogs are not shown yet (permission requests are
rejected). The configuration file is read and
validated by the CLI, and secrets can be stored in the keyring (see Configuration).
The ACP client (`app/backends/acp.py`, one process per agent, restarted after a crash at most
3 times per 60 s) also works from the terminal: `chat` runs one turn with any configured agent
and `test-agent` checks the connection (see Chatting from the terminal).

## System requirements

Ubuntu 26.04 / GNOME 50 (Wayland), Python ≥ 3.12 with PyGObject, GTK 4, libadwaita, GJS, Node.js
≥ 20.19 and npm. Packages that need `sudo` (install once):

```bash
sudo apt install gir1.2-webkit-6.0 xvfb libsecret-tools
```

`make setup` runs `scripts/check-deps.sh` first; when something is missing it prints the exact
`sudo apt install …` command and stops with exit code 1.

After `make setup`, Playwright WebKit needs some host libraries (on Ubuntu 26.04:
`libevent-2.1-7t64`, `libavif16`, `libmanette-0.2-0`):

```bash
sudo npx playwright install-deps webkit
```

Without them `make test-ui` still passes: it falls back to Chromium and prints a warning (see
Development).

## Running the application

```bash
.venv/bin/python -m app               # start (or show the window of the running instance)
.venv/bin/python -m app --background  # start without showing the window
gapplication action pl.local.AiPanel toggle   # also: show, hide, new-chat, quit
gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel \
    -m org.gtk.Actions.Describe visible       # read-only boolean state of the window
```

With `make`:

```bash
make run            # in the background on your desktop session; PID in .run/app.pid, log .run/app.log
make run-headless   # on a private Xvfb display and D-Bus bus, AI_PANEL_DEBUG=1
source .run/headless.env && gapplication action pl.local.AiPanel toggle
make stop           # stops either mode; also exits 0 when nothing runs
```

Both wait up to 10 s for `ui ready` in the log and exit 1 (with the last log lines) if it does
not appear. `make run-headless` keeps everything away from your session: `HOME` and
`XDG_CONFIG/DATA/STATE/CACHE_HOME` point into `.run/home`, `XDG_RUNTIME_DIR` is a fresh
`/tmp/ai-panel-runtime.*` directory (mode 0700) and `GIO_USE_VFS=local`, so the portals,
keyring and a11y services started on the private bus never touch `/run/user/<uid>` or your
keyring. `.run/headless.env` exports `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, these `XDG_*`
variables, `AI_PANEL_DEBUG=1` and `GDK_BACKEND=x11`; source it in the shell (or a subshell)
from which you send actions. `make stop` sends `quit`, sends SIGTERM after 3 s (SIGKILL after
3 s more) to the processes recorded in `.run/*.pid`, and removes the pid files, `headless.env`
and the runtime directory. It only signals processes whose command line matches what was
started.

The window talks to the agent chosen at start: `AI_PANEL_DEFAULT_AGENT` (agent id) if it
names a valid agent, otherwise `default_agent` from the configuration, otherwise the first valid
agent. Without agents the window shows the empty "add an agent" screen. The agent process starts
with the first prompt and keeps its session until `new-chat`; `quit` (and SIGTERM) stops it
(SIGTERM, SIGKILL after 3 s). Try it with the fake agents:

```bash
AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-slow make run-headless
```

Debug actions exist only when the app starts with `AI_PANEL_DEBUG=1` (`make run-headless`
sets it): `debug-send` types a prompt into the page and sends it the way Enter does (nothing is
sent while a turn runs), `debug-click` clicks the first element matching a CSS selector, and
`debug-dump` writes the page state to `$XDG_STATE_HOME/gnome-ai-panel/debug-dump.json` (mode
0600; format in PLAN §12.1, plus `busy` and the web view `uri`). `make cli ARGS="ui-dump"`
activates `debug-dump`, waits up to 5 s for the new file and prints it (exit 1 when the app is
not running with debug actions or no dump arrives):

```bash
AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml make run-headless && source .run/headless.env
gapplication action pl.local.AiPanel debug-send "'md: tabela'"
gapplication action pl.local.AiPanel debug-click "'a[data-external]'"
make -s cli ARGS="ui-dump"
```

`gapplication list-actions` needs an installed `.desktop` file (stage S6); until then list the
actions with `gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m
org.gtk.Actions.List`.

Links: the web view only shows `app/ui/index.html`. A click on an `http`, `https` or `mailto`
link opens it with `Gtk.UriLauncher`; any other target (relative paths, `file:`, `data:` …) is
blocked, and so are new windows. With `AI_PANEL_URI_LOG=/path/file` the URIs are appended to
that file instead of being opened (tests). The context menu has no navigation, download or
new-window entries; "Reload" and "Inspect Element" appear only with `AI_PANEL_DEBUG=1`.

Theme: `chat.theme = "light"` or `"dark"` forces the scheme of the window and the page;
`"system"` follows GNOME (`Adw.StyleManager`) and the page switches when the desktop does.
`chat.font_size` sets the base font size of the page in px.

Only one instance runs; starting it again activates the running one. Closing the window hides
it, only the `quit` action (or SIGTERM) ends the process. Logs go to stderr and to
`$XDG_STATE_HOME/gnome-ai-panel/app.log` (default `~/.local/state/…`, rotated at 1 MB, 3 files);
the level is set with `AI_PANEL_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Without a
display you can try it with `xvfb-run -a dbus-run-session -- .venv/bin/python -m app`.

asyncio runs directly on the GLib main loop (`gi.events.GLibEventLoopPolicy`, PyGObject ≥ 3.50).
`tests/unit/test_asyncio_glib.py` checks that subprocesses and timers work on it, so the
worker-thread fallback from the plan is not needed.

## Configuration

Agents, MCP servers and chat appearance live in `~/.config/gnome-ai-panel/config.toml`
(`$XDG_CONFIG_HOME/gnome-ai-panel/config.toml`; `AI_PANEL_CONFIG` overrides the path). Nothing
is preconfigured: a missing file means an empty, valid configuration, and the file is never
created automatically. `tests/data/config_valid.toml` contains the format example from the
spec (§5.3).

```bash
make cli ARGS="check-config"                       # or: --config path/to/config.toml
make cli ARGS="agents"                             # valid agents (id, type, name)
make cli ARGS="agents --json"
```

`check-config` prints one line per problem, `path: message` (e.g.
`agents.broken.command: wymagane`; problems of the whole file, such as TOML syntax errors, are
printed as `file:line: message`), then warnings prefixed with `ostrzeżenie: `. It exits 1 when
there are errors and 0 otherwise (warnings do not fail). Note that `make` itself exits with 2
whenever the command fails; run `.venv/bin/python -m app.cli check-config` to get the exact
exit code. An invalid `[agents.x]` or `[mcp.x]` entry is skipped and the rest keeps working;
an invalid `[chat]` value falls back to its default; unknown keys only produce warnings.

Warnings are given for a `literal` value source whose variable name contains `KEY`, `TOKEN`,
`SECRET` or `PASSWORD` (any case), and when the file is writable by group or others
(`chmod 600 ~/.config/gnome-ai-panel/config.toml`).

Value sources (`env.NAME = { source = "…", … }` of an agent or MCP server, `api_key` of an API
agent):

| Source | Keys | Value |
|---|---|---|
| `keyring` | `name` | item `name` of the libsecret schema `pl.local.AiPanel.Secret` (GNOME Keyring) |
| `env` | `name` | environment variable of the app |
| `command` | `cmd`, `timeout_s` (default 10) | stdout of `cmd` without trailing newlines; run without a shell (`shlex.split`), stdin closed, stderr discarded |
| `prompt` | `label` | asked when needed (CLI: hidden input on a terminal; without a terminal it is an error "wymaga interakcji") |
| `literal` | `value` | the value written in the file |

A source without a value (unset variable, no keyring item, cancelled prompt) is not an error:
the variable is left out of the agent's environment and the log names the variable (never the
value). A failing command is an error with the program name and exit code only. Resolved
secrets are replaced with `[redacted]` in the log.

Keyring commands (exit code 0 on success; 1 on error, for a missing item and for `has` when
the item does not exist):

```bash
printf '%s' 'sk-…' | make cli ARGS="secret set anthropic"   # value from stdin (hidden prompt on a TTY)
make cli ARGS="secret has anthropic"
make cli ARGS="secret delete anthropic"
```

The keyring is used only when the Secret Service (`org.freedesktop.secrets`, e.g.
gnome-keyring) is already running on the session bus; the app never starts it through D-Bus
activation. Without it the commands print `błąd: brak usługi Secret Service …` and exit 1.

Paths: `~` and `$VARIABLES` are expanded in `cwd`, `chat.history_dir`, in `command` when it
contains a `/`, and in `args` items starting with `~`, `./` or `../`. Relative paths are
resolved against the directory of the configuration file. A bare command such as `kiro-cli`
is looked up in `PATH` when the agent starts.

## Chatting from the terminal

```bash
make cli ARGS="test-agent ID"                     # start, initialize, session/new, stop
make cli ARGS="chat ID 'prompt'"                  # one turn, streamed to stdout
make cli ARGS="chat ID 'prompt' --json"           # JSON Lines, one event per line
make cli ARGS="chat ID 'prompt' --permission allow --cancel-after 5"
```

`test-agent` prints the agent name and version, `protokół: 1` and the login methods the agent
offers, then `OK: …` (exit 0) or `Test połączenia nie powiódł się: …` with a hint (exit 2):
missing command, unsupported protocol version, login required (with the agent's methods),
timeout (`startup_timeout_s`) or a crash with the last stderr lines.

`chat` streams the reply text as it arrives. Thinking, tool calls, permission requests, usage
and session options are separate lines prefixed with `[thinking]`, `[tool]`, `[permission]`,
`[usage]`, `[options]`; a stop reason other than `end_turn` is printed as `[done] <reason>`;
errors go to stderr as `błąd: …`. Permission requests are rejected by default and the line
says so; `--permission allow` picks the agent's "allow once" option. `--cancel-after S` sends
`session/cancel` after S seconds (the turn ends with `cancelled`). With `--json` every line is
one event (`{"type": "text_delta", "text": …}`, `tool_call`, `permission_request`, …, plus
`{"type": "permission_response", "request_id", "option_id", "allowed"}` after each answer); the
last line is `{"type": "done", "stop_reason": …}` or `{"type": "error", …}`.

Exit codes of both commands: 0 = success (`chat`: the turn ended, also when cancelled), 2 =
agent error, unknown agent ID (the available IDs are listed on stderr) or an agent type that is
not supported yet (`api`), 130 = Ctrl+C. Through `make` a failure always shows as exit code 2
of `make`; use `.venv/bin/python -m app.cli …` for the exact code. Both commands append to the
log file; on stderr they show only log errors unless `AI_PANEL_LOG_LEVEL` is set.

`tests/data/config_fake.toml` defines one agent per scenario of the fake ACP agent
(`fake-echo`, `fake-thinking`, `fake-tool`, `fake-perm`, `fake-slow`, `fake-crash`,
`fake-crash-once`, `fake-badver`, `fake-auth`, `fake-noise`, `fake-models`, `fake-load`,
`fake-usage`, `fake-image`, `fake-env`) plus `fake-missing` (`command = "/nonexistent/agent"`).
The agents work in `~/.cache/gnome-ai-panel-fake/<scenario>`; `fake-crash-once` crashes only
on the first prompt after its marker file there is removed.

```bash
AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-echo 'Cześć'"
AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-env SECRET_VAR"  # s3cr3t-value
```

## Development

| Command | What it does |
|---|---|
| `make setup` | checks system packages, creates `.venv` (with system site packages for `gi`), installs `requirements-dev.txt`, `npm ci`, installs Playwright WebKit and Chromium |
| `make build` | byte-compiles Python; later also compiles GSettings schemas and packs the extension into `dist/` |
| `make lint` | `ruff check`, `ruff format --check`, ESLint, GSettings schema check |
| `make test` | `make test-py test-gjs test-ui` (pytest under Xvfb and a private D-Bus, GJS unit tests, Playwright) |
| `make test-ui` | Playwright on `app/ui/index.html` with `tests/ui/mock-bridge.js`; browser from `PW_BROWSER`, see below |
| `make run` | starts the app in the background on the current session |
| `make run-headless` | starts the app on a private Xvfb display and D-Bus bus with isolated `HOME`/`XDG_*` |
| `make stop` | stops what `make run` / `make run-headless` started |
| `make vendor` | copies marked, DOMPurify and highlight.js (with the GitHub light/dark styles) from `node_modules` into `app/ui/vendor/` |
| `make cli ARGS="…"` | runs `python -m app.cli …` (`check-config`, `agents`, `secret`, `chat`, `test-agent`, `ui-dump`) |

Tests never touch your real `~/.config`, keyring or session bus: the `isolated_env` fixture
redirects `HOME` and `XDG_*` into a temporary directory and `make test-py` runs inside
`dbus-run-session` with a temporary `XDG_RUNTIME_DIR` and `GIO_USE_VFS=local`. Integration
tests (`tests/integration/`, marker `gui`) start `python -m app` as a subprocess on a private
bus of their own (`app_process` fixture) and drive it with `gapplication`/`gdbus`; the tests of
the run scripts set `AI_PANEL_RUN_DIR` so your `.run/` and a running instance are left alone. The
keyring tests (`tests/integration/test_libsecret.py`) start their own `dbus-daemon` and an
unlocked `gnome-keyring-daemon` with keyring files under the test's temporary directory; they
are skipped when `gnome-keyring-daemon` is missing or does not start.

The chat page uses only local files. `app/ui/vendor/` is committed and holds unmodified copies
of `marked` (`lib/marked.umd.js`), `dompurify` (`dist/purify.min.js`) and
`@highlightjs/cdn-assets` (the prebuilt `highlight.min.js` with the common languages,
`styles/github.min.css`, `styles/github-dark.min.css`), their license files and `vendor.json`
(versions and SHA-256 of every file). The versions come from `package-lock.json`. To update
a library, change its version in `package.json`, run `npm install` and `make vendor`, and commit
the result. `make vendor` stops with an error when `node_modules` does not match the lock file
(run `npm ci` first) and removes vendored files that are no longer listed in
`scripts/vendor.mjs`. `app/ui/render.js` turns markdown into sanitised HTML
(`window.aiPanelRender.renderMarkdown`) and adds highlighting and a copy button to code blocks
(`enhanceCodeBlocks`). `app/ui/chat.js` holds the chat screen: the message list, the prompt
(Enter sends `{type: "send", text}`, Shift+Enter adds a line, the field grows up to 8 lines),
the stop button (`{type: "cancel"}`) and the handlers of `init`, `turn_start`, `text_delta`
(rendered at most once per animation frame), `done` and `error` that Python calls through
`window.aiPanel.dispatch(obj)`, plus `conversation` (clears the list on `new-chat`);
`tests/ui/chat.spec.mjs` drives them with the mock bridge. On the Python side `app/bridge.py`
checks the fields of every page message (an invalid `send` is answered with `error`, other
invalid or unknown messages are logged as warnings and dropped) and dispatches events with
`evaluate_javascript`, the JSON escaped so that `</script>` and U+2028 cannot break out.
`app/controller.py` (`ChatController`, no GTK) keeps the conversation in memory, creates the
agent session at the first prompt and answers every `send` with exactly one `done` or `error`
(also when it is rejected because a turn is running or there is no agent); nothing of a turn is
dispatched after its `done`/`error`, and repeated `cancel` messages count as one.

Environment variables used by the app and tests are listed in `.env.example`.

`tests/fakes/fake_acp_agent.py --scenario NAME [--record FILE]` is a stand-alone fake ACP agent
(stdlib only) used by the tests; the scenarios are listed in its docstring. Try it with:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' \
    | .venv/bin/python tests/fakes/fake_acp_agent.py --scenario echo
```

Playwright browser: when `PW_BROWSER` is unset, `make test-ui` runs `scripts/pick-browser.mjs`,
which tries to launch WebKit (the engine closest to WebKitGTK). If WebKit cannot start, it
prints `test-ui: Playwright WebKit cannot launch on this machine, falling back to chromium.`
with the launch error on stderr and the tests run on Chromium. `PW_BROWSER=webkit` or
`PW_BROWSER=chromium` forces a browser without fallback, so `PW_BROWSER=webkit make test-ui`
fails when the WebKit libraries are missing.

## License

Not decided yet.
