# Implementation report S1-T3 attempt 1

## Changes
- `scripts/run-common.sh` (new, sourced): paths (`.run/` or `$AI_PANEL_RUN_DIR`), pid-file helpers, `wait_ready` (≤ 10 s for `ui ready`). `running <pidfile> <match>` only reports a pid when the process is alive **and** its `/proc/<pid>/cmdline` contains the expected string (`-m app`, `Xvfb`, `dbus-daemon`), so reused pids are never signalled.
- `scripts/run.sh` (new): `make run`. Starts `.venv/bin/python -m app --background` with `setsid`, PID in `.run/app.pid`, output in `.run/app.log`, waits for `ui ready`. Already running → exit 0. A headless instance running → exit 1 with a hint. If the process exits 0 before `ui ready` (GApplication handed over to an instance already on the session bus) → exit 0 with a message. Timeout or crash → stop, last 20 log lines, exit 1.
- `scripts/run-headless.sh` (new): `make run-headless`.
  - Xvfb with `-displayfd` and `-nolisten tcp`.
  - `HOME`/`XDG_{CONFIG,DATA,STATE,CACHE}_HOME` in `.run/home` (0700).
  - **Tester feedback:** `XDG_RUNTIME_DIR` is a fresh `mktemp -d /tmp/ai-panel-runtime.XXXXXX` (0700), and `GIO_USE_VFS=local` is set.
  - `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, `GNOME_KEYRING_CONTROL`, `SSH_AUTH_SOCK`, `SESSION_MANAGER`, `XAUTHORITY` and `AT_SPI_BUS_ADDRESS` are unset.
  - The private bus is started with `dbus-daemon --session --fork --print-address=1 --print-pid=1` after these exports, so the portals, gnome-keyring and at-spi it activates inherit the isolated environment. I checked this: the keyring and portal use `/tmp/ai-panel-runtime.*`, not `/run/user/1000`.
  - Writes `.run/headless.env` (`DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, `XDG_*` including `XDG_RUNTIME_DIR`, `GIO_USE_VFS`, `AI_PANEL_DEBUG=1`, `GDK_BACKEND=x11`, `WEBKIT_DISABLE_COMPOSITING_MODE`, `LIBGL_ALWAYS_SOFTWARE`, `NO_AT_BRIDGE`, plus `unset WAYLAND_DISPLAY`), with values quoted by `printf %q`. It does not export `HOME`, so sourcing it does not change the user's shell home.
  - On any failure the `EXIT` trap calls `stop.sh` and prints the log tail.
- `scripts/stop.sh` (new): `make stop`.
  - Sends `gapplication action … quit` (inside a subshell that sources `headless.env` in headless mode), waits ≤ 3 s, then SIGTERM, then SIGKILL after 3 s more, for app, dbus-daemon and Xvfb from `.run/*.pid`.
  - Removes the pid files, `headless.env` and the runtime dir. It only removes paths matching `*/ai-panel-runtime.*`, waits for the portal's FUSE `doc` mount to go away, and uses `rm -rf --one-file-system`.
  - Exits 0 when nothing runs. Garbage or foreign pid files are dropped without signalling anything.
- `Makefile`:
  - `run`, `run-headless` and `stop` call the scripts.
  - `test-ui` picks the browser with `scripts/pick-browser.mjs`.
  - `test-py` now runs with a temporary `XDG_RUNTIME_DIR` (`mktemp -d`, removed afterwards), `GIO_USE_VFS=local`, and without `GNOME_KEYRING_CONTROL`/`SSH_AUTH_SOCK`/`WAYLAND_DISPLAY`/`AT_SPI_BUS_ADDRESS`. This removed the `fusermount3 … /run/user/1000/gvfs` and `GNOME_KEYRING_CONTROL=/run/user/1000/keyring` messages that the S1-T2 tester saw.
  - ESLint also covers `scripts/`.
- `scripts/pick-browser.mjs` (new): the Playwright fallback. See "Playwright browser choice" below.
- `tests/ui/mock-bridge.js` (new): an init script that installs `window.webkit.messageHandlers.bridge`. It records each `postMessage` (deep copy) in `window.__bridge.messages` and offers `window.__bridge.dispatch(obj)` → `window.aiPanel.dispatch`. It first tries to add `bridge` to an existing `window.webkit.messageHandlers` (Playwright WebKit), falls back to replacing `window.webkit`, and throws if neither works.
- `tests/ui/smoke.spec.mjs` (new): loads `app/ui/index.html` via `file://`. Checks: title, `#empty-state` visible, „Dodaj agenta", no page errors, one CSP `meta` with `default-src 'none'`/`script-src 'self'`, and that the bridge got exactly `[{type:"ready"}]`.
- `tests/integration/conftest.py` (new):
  - `app_env`: built on `isolated_env`. Adds a temporary `XDG_RUNTIME_DIR` (0700), `GIO_USE_VFS=local`, `GDK_BACKEND=x11`, `AI_PANEL_DEBUG=1` and the software rendering variables, and drops the session variables.
  - `private_bus`: its own `dbus-daemon`, stopped afterwards.
  - `app_process`: a factory that starts `python -m app …`, waits for `ui ready` in the isolated log, and on teardown sends `quit` → wait 5 s → SIGTERM → SIGKILL. `AppProcess` has `action()`, `visible()`, `name_owner_pid()` and `run()`.
- `tests/integration/test_app_actions.py` (new, marker `gui`):
  - `toggle` false→true→false;
  - `show`/`hide`;
  - the action list via `org.gtk.Actions.List`;
  - a second `python -m app --background` exits 0, the bus-name owner pid stays the same and the window stays hidden; a later `python -m app` exits 0 and shows the window; `ui ready` was logged once;
  - `quit` → exit 0 in ≤ 5 s and the name is released;
  - the app's `/proc/<pid>/environ` has the temporary `XDG_RUNTIME_DIR` and `GIO_USE_VFS=local`.
- `tests/integration/test_run_scripts.py` (new, marker `gui`, uses `AI_PANEL_RUN_DIR=tmp_path`):
  - full `run-headless.sh` → `headless.env` contents, runtime dir 0700 outside `/run/user`, `show`/`toggle` via the sourced env, a second run → "already running" → `stop.sh` kills app, Xvfb and dbus, removes pid files, env and runtime dir → a second `stop.sh` exits 0;
  - `stop.sh` with nothing running;
  - pid files pointing at an unrelated `sleep` → not signalled, and a runtime-dir file pointing outside `ai-panel-runtime.*` → not deleted;
  - garbage pid files.
- `.env.example`: added `AI_PANEL_RUN_DIR`. `PW_BROWSER` is now empty by default, with the fallback described.
- `README.md`: `make run`/`run-headless`/`stop` usage and isolation, the WebKit host libraries, the test isolation, and the Playwright browser choice.

## Playwright browser choice
- When `PW_BROWSER` is unset, `make test-ui` runs `node scripts/pick-browser.mjs`, which tries `webkit.launch()`.
  - If the launch works, it prints `webkit`.
  - If it fails, it prints `chromium` and writes to stderr: `test-ui: Playwright WebKit cannot launch on this machine, falling back to chromium.`, the `sudo npx playwright install-deps webkit` hint, and the first lines of the launch error (which list the missing libraries).
  - The Makefile prints `test-ui: PW_BROWSER=<chosen>` and runs Playwright with it.
- When `PW_BROWSER` is set, it is used as is with no fallback, so `PW_BROWSER=webkit make test-ui` fails loudly while the libraries are missing.
- `playwright.config.mjs` still defaults to `webkit` when it is called directly (`npx playwright test`).
- **WebKit check:** I did not run sudo. I downloaded the .debs with `apt-get download` (`libevent-2.1-7t64`, `libavif16`, `libmanette-0.2-0`, plus `libgav1-2` and `libhidapi-hidraw0`), unpacked them into `/tmp/aip-wklibs`, and ran with `LD_PRELOAD` of those libraries. With that, `pick-browser.mjs` printed `webkit` and `PW_BROWSER=webkit npx playwright test` passed 3/3. The mock bridge and smoke test therefore work on real Playwright WebKit. `LD_LIBRARY_PATH` alone was not enough, because `MiniBrowser`'s wrapper overwrites it.

## Problems from previous report
- No `S1-T3-test-*.md` existed.
- S1-T2 tester suggestion 1 (isolate `XDG_RUNTIME_DIR`, `GIO_USE_VFS=local`) → done in `run-headless.sh`, in the `app_env` fixture and in `make test-py`. It is checked by `test_app_environment_is_isolated` and `test_run_headless_show_toggle_and_stop`.
- Suggestions 2–4 (NFR-2 `decide-policy`, the `MAX_MESSAGE_BYTES` name, PyGObject deprecation warnings) are out of S1-T3 scope. Navigation policy is part of S3-T4. Not changed.

## How to verify
- `make run-headless; echo $?` → `0`. `.run/headless.env` exists.
- `source .run/headless.env && gapplication action pl.local.AiPanel show && gdbus call --session -d pl.local.AiPanel -o /pl/local/AiPanel -m org.gtk.Actions.Describe visible` → `((true, signature '', [<true>]),)`. After `toggle` → `[<false>]`.
- `grep -c "ui ready" .run/home/state/gnome-ai-panel/app.log` → ≥ 1. The log is kept across runs, so the count grows.
- `make stop; echo $?` → `0`. No `python -m app`, Xvfb or dbus-daemon left from `.run/*.pid`, and no `/tmp/ai-panel-runtime.*`. Running `make stop` again → `0`.
- `make run` → `0` ("ui ready"). A second `make run` → `0` ("already running"). `make run-headless` while it runs → `1` with a hint. `make stop` → `0`.
- `make test` → `0`. Its output includes `test-ui: PW_BROWSER=chromium` and the fallback warning on this machine.
- `PW_BROWSER=chromium make test-ui` → 3 passed.

## Command results
- build: ok, lint: ok, test: 86/86 (pytest 82/82 including 10 new integration tests, gjs 1/1, Playwright 3/3 on Chromium through the automatic fallback)

## Known limitations / deviations from plan
- `make test-ui` behaviour differs slightly from the PLAN table ("`npx playwright test`, default `webkit`"). WebKit is still the default, but when it cannot launch and `PW_BROWSER` is unset, the run falls back to Chromium automatically with a warning. This is the PLAN §7 risk mitigation (`PW_BROWSER=chromium` as fallback), applied automatically so that `make test` passes here without sudo.
- `make test-py` sets a temporary `XDG_RUNTIME_DIR` and `GIO_USE_VFS=local` in addition to the PLAN command. This is required by the tester's isolation feedback.
- `gapplication list-actions pl.local.AiPanel` needs an installed `.desktop` file (it fails with "cannot find .desktop file" until `make install` in S6). The test uses `gdbus … org.gtk.Actions.List` instead. This matters for the S3-T4 "Done when", which uses `gapplication list-actions`.
- Under the private bus, xdg-desktop-portal still prints harmless warnings (no Mutter service channel, no PipeWire).
- `/tmp/aip-wklibs` (about 1 MB of unpacked .deb files, used only for the WebKit check) is still on disk. The tool sandbox blocked `rm -rf` on it. It can be deleted by hand.
- Nothing was committed, and `.pipeline/STATE.md`/`TASKS.md` were not edited. No background processes were left running.
