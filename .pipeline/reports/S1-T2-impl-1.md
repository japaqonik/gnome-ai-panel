# Implementation report S1-T2 attempt 1

## Changes
- `app/__main__.py`: `python -m app` calls `app.main.main()` and exits with its return code.
- `app/main.py`: `AiPanelApplication(Adw.Application)` with `application_id="pl.local.AiPanel"`.
  - Actions `toggle`, `show`, `hide`, `new-chat` (logs only until S3) and `quit`.
  - `visible` is a stateful `b` action. Its state follows the window's `notify::visible`; `activate` and `SetState` from outside are ignored, so it is read-only.
  - `hold()` runs in `startup`. A SIGTERM handler (`GLibUnix.signal_add`) calls `quit()`.
  - `--background` is a main option. In `handle-local-options` the app registers first. If another instance is already running it returns 0 without activating it, so its window is not shown. Otherwise the first `activate` does not present the window.
  - `main()` sets up logging and runs the app inside `with GLibEventLoopPolicy():`, so `Gio.Application.run` also drives asyncio.
  - GTK/WebKit windows are created only in `do_startup`, and `window`/`bridge` are imported lazily there, so `import app.main` works without a display.
- `app/window.py`: `PanelWindow(Adw.ApplicationWindow)` with `set_decorated(False)`, a default size of 480×900 and `set_hide_on_close(True)`, so closing hides the window instead of destroying it. It holds a `WebKit.WebView` that loads `app/ui/index.html` through a `file://` URI. Developer extras are on only when `AI_PANEL_DEBUG=1`.
- `app/bridge.py`: registers the `bridge` script message handler on the `UserContentManager`. `parse_message` drops anything that is not a JSON object with a non-empty string `type`, or that is larger than 32 MiB, and logs a warning. `ready` logs `ui ready` at INFO; other types are logged at DEBUG.
- `app/logging_setup.py`: the `app` logger writes to stderr and to `$XDG_STATE_HOME/gnome-ai-panel/app.log` (default `~/.local/state`, directory `0700`). The file rotates at 1 MB with 3 backups. The level comes from `AI_PANEL_LOG_LEVEL`; an invalid value falls back to INFO with a warning. Calling setup again does not duplicate handlers.
- `app/ui/index.html`: contains the CSP from NFR-2 verbatim and the `#empty-state` section ("Brak skonfigurowanych agentów" plus a "Dodaj agenta" button). It loads only local resources.
- `app/ui/app.js`: a classic `defer` script, not a module, because Chromium blocks module scripts on `file://` and Chromium is the Playwright fallback. It sends `{type:"ready"}` through `window.webkit.messageHandlers.bridge` when that handler exists.
- `app/ui/style.css`: light and dark colours via `prefers-color-scheme`, a centred empty state and a visible focus ring.
- New tests:
  - `tests/unit/test_asyncio_glib.py`: on a fresh `GLibEventLoop`, `create_subprocess_exec("true")`, a subprocess with stdout/stderr pipes and exit code 3, and `asyncio.sleep(0.1)` all work. The same checks also run inside `Gio.Application.run` through `create_asyncio_task`, which is how the app uses the loop.
  - `tests/unit/test_actions.py`: the action set, that simple actions have no state or parameter, that `visible` has type `b`, starts `false` and is read-only, that actions without a window do not fail, that `import app.main` without `DISPLAY`/`WAYLAND_DISPLAY` creates no toplevels, and that `--help` lists `--background`. None of these register the application on the bus.
  - `tests/unit/test_logging_setup.py` and `tests/unit/test_bridge.py`: level parsing, the file path and permissions, no duplicate handlers, message validation, `ui ready`, and the CSP and empty state in `index.html`.
- `README.md`: updated the status line and added a "Running the application" section with the commands, actions, log location and the asyncio decision.

## Problems from previous report
- There was no `S1-T2-test-*.md` and no feedback was attached. The non-blocking suggestions in S1-T1-test-1 (README "exit code 1" wording, Polish messages in `check-deps.sh`) belong to S1-T1 and were left as they are.

## How to verify
- `env -u DISPLAY -u WAYLAND_DISPLAY .venv/bin/python -c "import app.main"` → exit 0.
- `xvfb-run -a dbus-run-session -- .venv/bin/python -m app` with isolated `HOME`/`XDG_STATE_HOME` logs `INFO app.bridge: ui ready` about 1.2 s after start, which meets the ≤ 10 s requirement.
- In the same session I checked these by hand:
  - `org.gtk.Actions.List` → `['new-chat','toggle','hide','show','quit','visible']`.
  - `toggle` changes `visible` from false to true, a second `toggle` changes it back to false, and `show` sets it to true.
  - `SetState visible false` leaves it `true`, and `hide` sets it to false.
  - A second `python -m app --background` exits 0 and the window stays hidden. A second `python -m app` exits 0 and shows the window.
  - `quit` ends the process in ≤ 0.5 s with exit 0. SIGTERM also ends it with exit 0.
  - No processes were left running.
- `make lint` → 0, `make build` → 0, `make test` → 0.

## Command results
- build: ok, lint: ok, test: 55/55 (pytest 54/54, gjs 1/1, Playwright 0 specs with `--pass-with-no-tests`, exit 0)

## Known limitations / deviations from plan
- **asyncio: plan A works, plan B is not needed.** On PyGObject 3.56.2 with Python 3.14.4, `asyncio.create_subprocess_exec`, pipes, `wait()` and `asyncio.sleep` work on `GLibEventLoop`, both standalone and under `Gio.Application.run`. The README records this.
- Python 3.14 prints `DeprecationWarning` for `asyncio.*_event_loop_policy`, and PyGObject's own code prints a `PyGIDeprecationWarning` for `GLib.unix_signal_add_full`. Both are harmless now. Python 3.16 removes policies; PyGObject's docstring says "FIXME: say what to do in the future". When that happens, the replacement is `GLibEventLoop` with `asyncio.set_event_loop`, or a newer PyGObject API.
- `Gio.ActionGroup.list_actions()` needs a registered application. Because `test_actions.py` must not register on the bus, it checks each action with `lookup_action` plus the module constants `SIMPLE_ACTIONS`/`STATE_ACTIONS`. The real D-Bus list was checked by hand (above) and will be covered by the S1-T3 integration tests.
- `new-chat` only logs for now; conversations come with the controller in S3.
- Under `dbus-run-session`, xdg-desktop-portal and the a11y bus print warnings to stderr ("Failed to open service channel…", "A connection to the bus can't be made"). These come from the isolated environment, not from the app, and they do not affect the tests.
- No system packages are missing for this task. The Playwright WebKit host libraries from S1-T1 (`libevent-2.1-7t64`, `libavif16`, `libmanette-0.2-0`) are still needed by S1-T3, or `PW_BROWSER=chromium` can be used instead.
- Nothing was committed, and `.pipeline/STATE.md`/`TASKS.md` were not edited.
