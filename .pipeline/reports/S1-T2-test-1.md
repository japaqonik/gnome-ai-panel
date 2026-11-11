# Test report S1-T2 attempt 1
Verdict: PASS

## Command results
- build: `make build` → exit 0
- lint: `make lint` → exit 0 (also after the tests added below)
- test: `make test` → exit 0. Before my additions: pytest 54/54, gjs 1/1, Playwright 0 specs. After my additions: pytest 72/72, gjs 1/1, Playwright 0 specs (`--pass-with-no-tests`).

## Done-when criteria
- [x] `xvfb-run -a dbus-run-session -- .venv/bin/python -m app` started in the background logs `ui ready` in ≤ 10 s. Evidence: run with `HOME`/`XDG_*` in `/tmp/aip-*`, `GDK_BACKEND=x11`, `WAYLAND_DISPLAY` unset. `ui ready` appeared on stderr after 1.46 s, and `grep -c "ui ready" $XDG_STATE_HOME/gnome-ai-panel/app.log` returned 1.
- [x] `.venv/bin/python -c "import app.main"` works without a display. Evidence: `test_import_main_needs_no_display` runs it with `DISPLAY`/`WAYLAND_DISPLAY` removed, and it exits 0 with no toplevels.
- [x] `make lint` and `make test` → exit 0 (see above).
- [x] Tests listed in the task exist and pass. `test_asyncio_glib.py` covers `create_subprocess_exec("true")`, pipes with exit code 3, and `asyncio.sleep`, both on a new loop and inside `Gio.Application.run`, so plan A applies and the README records it. `test_actions.py` checks the action set and that `visible` has type `b`, without registering on the bus.

## Exploratory checks (private bus under xvfb-run + dbus-run-session, isolated XDG)
- `org.gtk.Actions.List` → `['new-chat','toggle','hide','show','quit','visible']`.
- `visible` is `true` after a plain start. `toggle` sets it to false, a second `toggle` to true. `show` keeps it true and `hide` sets it to false.
- `visible` is read-only: `SetState visible <false>` and `Activate visible` both leave the state unchanged (`true`).
- `new-chat` → exit 0. An unknown action `bogus` → D-Bus `InvalidArgs` and exit 1 from `gapplication`, which is the expected behaviour.
- A second `python -m app --background` → exit 0 and the window stays hidden. A second `python -m app` → exit 0 and the window is shown. Only one app process ran.
- `quit` ends the process in 0.08 s with exit 0. Starting with `--background` logs `started in background`, still reaches `ui ready`, and has `visible=false`. SIGTERM → exit 0.
- `AI_PANEL_LOG_LEVEL=bogus` → WARNING and INFO is used. The log directory has mode 0700.
- No app processes were left running afterwards.

## Tests added
- `tests/unit/test_window.py` (marker `gui`, skipped without a display, the app is never registered on D-Bus):
  - window properties: undecorated, 480×900, hide-on-close, `file://` URI of `app/ui/index.html`, developer extras off without `AI_PANEL_DEBUG`;
  - the real page sends `{type:"ready"}` through the WebKit handler to `Bridge`;
  - `close()` hides the window without destroying it, and it can be shown again;
  - invalid `postMessage` payloads from the page are dropped (string, number, `{}`, empty or non-string `type`, array, `null`);
  - a valid unknown type is routed to `handle`.
- `tests/unit/test_logging_edge.py`: an unwritable state dir falls back to stderr with a warning and no crash; level parsing ignores case and surrounding spaces; rotation is 1 MiB × 3; no propagation to the root logger.

All new tests pass. None exposed a bug.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
1. The isolated test environment still reaches `/run/user/1000`. Under `dbus-run-session`, GTK activates `org.gtk.vfs.Daemon` (stderr: `fusermount3: failed to access mountpoint /run/user/1000/gvfs`) and a keyring helper prints `discover_other_daemon: GNOME_KEYRING_CONTROL=/run/user/1000/keyring`. Nothing was written to the user's keyring, but `XDG_RUNTIME_DIR` is not isolated. For S1-T3 (`run-headless.sh`, `app_process`), consider a temporary `XDG_RUNTIME_DIR` and/or `GIO_USE_VFS=local`.
2. NFR-2 says navigation outside `file://…/app/ui/` must be blocked. S1-T2 does not list it in its scope, but `PanelWindow` has no `decide-policy` handler yet. It should be scheduled explicitly (S3 or later).
3. `MAX_MESSAGE_BYTES` in `app/bridge.py` is compared against `len(raw)`, which counts characters, not bytes. This is harmless as an upper bound, but the name is misleading.
4. Calls to `MainContext.iteration` emit PyGObject `DeprecationWarning`s (`asyncio.get_event_loop_policy`), more than 1000 per run. `test_window.py` filters them. The Python 3.16 follow-up is already noted in the implementation report.
