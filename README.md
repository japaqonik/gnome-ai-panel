# GNOME AI Panel

Side panel for GNOME (Wayland, GNOME Shell 50) with a chat window that talks to any agent
speaking the [Agent Client Protocol](https://agentclientprotocol.com) (e.g. `kiro-cli acp`,
`claude-agent-acp`) or directly to the Anthropic Messages API. The project consists of:

- the application `pl.local.AiPanel` (Python, GTK 4, libadwaita, WebKitGTK) running in the
  background and controlled through D-Bus actions,
- a GNOME Shell extension that docks the window to a screen edge and toggles it with a shortcut.

Status: early development (stage S1). The application starts, shows an empty chat page and
answers the D-Bus actions below; it cannot talk to agents yet.

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

Only one instance runs; starting it again activates the running one. Closing the window hides
it, only the `quit` action (or SIGTERM) ends the process. Logs go to stderr and to
`$XDG_STATE_HOME/gnome-ai-panel/app.log` (default `~/.local/state/…`, rotated at 1 MB, 3 files);
the level is set with `AI_PANEL_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Without a
display you can try it with `xvfb-run -a dbus-run-session -- .venv/bin/python -m app`.

asyncio runs directly on the GLib main loop (`gi.events.GLibEventLoopPolicy`, PyGObject ≥ 3.50).
`tests/unit/test_asyncio_glib.py` checks that subprocesses and timers work on it, so the
worker-thread fallback from the plan is not needed.

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

Tests never touch your real `~/.config`, keyring or session bus: the `isolated_env` fixture
redirects `HOME` and `XDG_*` into a temporary directory and `make test-py` runs inside
`dbus-run-session` with a temporary `XDG_RUNTIME_DIR` and `GIO_USE_VFS=local`. Integration
tests (`tests/integration/`, marker `gui`) start `python -m app` as a subprocess on a private
bus of their own (`app_process` fixture) and drive it with `gapplication`/`gdbus`; the tests of
the run scripts set `AI_PANEL_RUN_DIR` so your `.run/` and a running instance are left alone.

Environment variables used by the app and tests are listed in `.env.example`.
Playwright browser: when `PW_BROWSER` is unset, `make test-ui` runs `scripts/pick-browser.mjs`,
which tries to launch WebKit (the engine closest to WebKitGTK). If WebKit cannot start, it
prints `test-ui: Playwright WebKit cannot launch on this machine, falling back to chromium.`
with the launch error on stderr and the tests run on Chromium. `PW_BROWSER=webkit` or
`PW_BROWSER=chromium` forces a browser without fallback, so `PW_BROWSER=webkit make test-ui`
fails when the WebKit libraries are missing.

## License

Not decided yet.
