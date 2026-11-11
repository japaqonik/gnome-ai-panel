# Test report S1-T3 attempt 1
Verdict: PASS

## Command results
- build: `make build` → exit 0
- lint: `make lint` → exit 0 (also after my added tests)
- test: `make test` → exit 0. Before my additions: pytest 82/82, gjs 1/1, Playwright 3/3 (Chromium through the automatic fallback). After my additions: pytest 86/86, gjs 1/1, Playwright 3/3.
- `PW_BROWSER=webkit make test-ui` → exit 2, 3 failed (`libevent-2.1.so.7` missing). This is expected: an explicit choice gets no fallback. The fallback and the `sudo npx playwright install-deps webkit` hint are documented in README and `.env.example`. Without `PW_BROWSER`, `make test-ui` prints `test-ui: Playwright WebKit cannot launch on this machine, falling back to chromium.` plus the launch error.

## Done-when criteria
- [x] `make run-headless` → exit 0, and `.run/headless.env` exists. Evidence: exit 0 with `ui ready (pid …, DISPLAY=:2)`. `headless.env` exports `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` (`/tmp/dbus-…`), `XDG_{CONFIG,DATA,STATE,CACHE}_HOME` (under `.run/home`), `XDG_RUNTIME_DIR=/tmp/ai-panel-runtime.4r5GHR`, `GIO_USE_VFS=local`, `AI_PANEL_DEBUG=1` and `GDK_BACKEND=x11`.
- [x] `source .run/headless.env && gapplication action … show && gdbus … Describe visible` → `((true, signature '', [<true>]),)`. `toggle` → `[<false>]`, and `toggle` again → `[<true>]`. `grep -c "ui ready" .run/home/state/gnome-ai-panel/app.log` → 3 (the log is kept across runs).
- [x] `make stop` → exit 0 in 0.36 s. It printed app, dbus-daemon and Xvfb stopped. No app, Xvfb, dbus-daemon, portal, keyring or at-spi process with a pid above the session baseline was left. The runtime dir, pid files and `headless.env` were removed. A second `make stop` → exit 0.
- [x] `make test` → exit 0 (see above).
- [x] The tests from the task exist and pass: toggle false→true→false; a second start exits 0 and the bus-name owner pid is unchanged; `quit` exits in ≤ 5 s; Playwright checks `#empty-state`, the CSP meta tag and `{type:"ready"}`.

## Isolation check (requested)
- **run-headless:** `/proc/<app>/environ` has `XDG_RUNTIME_DIR=/tmp/ai-panel-runtime.*`, `GIO_USE_VFS=local`, `HOME=.run/home` and the private bus address. Every process activated on the private bus uses the temporary runtime dir and the private bus, not `/run/user/1000`. I checked this for xdg-desktop-portal(-gnome/-gtk), permission-store, document-portal, gnome-keyring-daemon, at-spi-bus-launcher and its dbus-daemon, and xdg-dbus-proxy. The document portal FUSE mount is `/tmp/ai-panel-runtime.*/doc`, and the keyring control dir is inside the temporary runtime dir.
- **Integration fixtures:** `app_env` creates `tmp_path/runtime` (mode 0700), sets `GIO_USE_VFS=local` and drops the session variables. The `private_bus` fixture runs its own dbus-daemon. `test_app_environment_is_isolated` checks `/proc/<pid>/environ`.
- **`make test-py`:** uses `mktemp -d` for `XDG_RUNTIME_DIR` and sets `GIO_USE_VFS=local`. The S1-T2 messages about `/run/user/1000/gvfs` and `/run/user/1000/keyring` are gone. Cleanup is not always complete (see suggestion 1).

## Tests added
`tests/integration/test_run_scripts.py` (marker `gui`, uses `AI_PANEL_RUN_DIR=tmp_path`):
- `test_run_headless_cleans_up_when_ui_never_gets_ready`: with `READY_TIMEOUT=0`, the script exits 1 with "no 'ui ready'". It leaves no pid files, `headless.env` or `runtime-dir`, and no live process that inherited this run dir.
- `test_stop_after_app_crash_still_stops_xvfb_and_bus`: the app is SIGKILLed, then `stop.sh` → exit 0. Xvfb and dbus are gone and the runtime dir is removed.
- `test_run_refuses_while_headless_instance_runs`: `run.sh` → exit 1 with a hint, and the headless app keeps running. It returns before it can reach the real session bus.
- `test_headless_env_does_not_change_home_and_hides_wayland`: sourcing `headless.env` keeps the caller's `HOME` and unsets `WAYLAND_DISPLAY`. The app runs with `HOME=<run>/home`, `GIO_USE_VFS=local` and no `/run/user` runtime dir.

All four pass. None of them exposed a bug.

## Problems (for the implementer; each actionable)
None blocking.

## Suggestions (non-blocking)
1. `make test-py` sometimes leaves its temporary runtime dir behind. It happened in 2 of 3 runs. The output shows `rm: nie można usunąć '/tmp/ai-panel-test-runtime.XXXX/doc': Jest katalogiem` (or "na innym urządzeniu"), and an empty `/tmp/ai-panel-test-runtime.*` dir is left. The cause is that the document portal's FUSE mount at `$rt/doc` is still being unmounted when `rm` runs right after `dbus-run-session` returns. `stop.sh` already waits for this mount (`mountpoint -q … doc`, then `fusermount3 -u`); the Makefile `test-py` recipe should do the same. To reproduce, run `make test-py; ls -d /tmp/ai-panel-test-runtime.*`. No processes leak, only empty dirs. I removed the leftovers.
2. The app under `run-headless` inherits `DBUS_STARTER_ADDRESS=unix:path=/run/user/1000/bus` and `DBUS_STARTER_BUS_TYPE=session` from the caller's environment. GLib's starter-bus lookup follows `DBUS_STARTER_BUS_TYPE=session` and so uses the private bus. libdbus users of `DBUS_BUS_STARTER` would reach the real bus, though. Consider adding both variables to the `unset` list in `run-headless.sh` and to `SESSION_VARS` in `tests/integration/conftest.py`.
3. The runtime-dir guard in `stop.sh` (`*/ai-panel-runtime.*`) also matches paths like `/tmp/ai-panel-runtime.x/../../somewhere`. Only the script writes `.run/runtime-dir`, so this is hardening only. A stricter check would be to resolve the path with `realpath` and require `"${TMPDIR:-/tmp}"/ai-panel-runtime.??????`.
4. `/tmp/aip-wklibs` (from the implementer's WebKit check) is still on disk. I left it alone.
5. Already known and correctly flagged by the implementer: `gapplication list-actions` needs an installed `.desktop` file, which affects the S3-T4 "Done when".
