# Test report S2-T2 attempt 1
Verdict: FAIL

## Command results
- build: `make build` → 0
- lint: `make lint` → 0
- test: `make test` → 0 (pytest 277/277 before my additions, GJS 1/1, Playwright 3/3 on the Chromium fallback because WebKit lacks `libevent-2.1.so.7`)
- With my new file `tests/unit/test_secrets_edge.py`: 11/12 pass, 1 fails (problem 1 below), so `make test` is now red until the fix.

## Done-when criteria
- [x] `printf 'abc' | make cli ARGS="secret set test-x"` without Secret Service → message, CLI code 1. Evidence: run under `env -i … dbus-run-session` with temporary HOME and XDG_RUNTIME_DIR: stderr `błąd: brak usługi Secret Service (keyring): usługa org.freedesktop.secrets nie działa; …`, make exits 2 (convention), `.venv/bin/python -m app.cli secret set test-x` exits 1, no traceback. `has` and `delete` also exit 1 with the same message. Missing NAME or subcommand → argparse usage, exit 2.
- [x] `make test` → 0 (with the implementer's tests; see above for the new failing test).
- Tests list from TASKS.md: each source, `printf secret`, `false`, `sleep 20` with 0.5 s timeout, unset `env` → `None`, redaction in log and `str(error)`, `LibsecretStore` integration skipped without service. All present in `tests/unit/test_secrets.py` and `tests/integration/test_libsecret.py`, and they assert behaviour.

## Isolation checks
- `tests/integration/test_libsecret.py` starts its own `dbus-daemon` and `gnome-keyring-daemon` with HOME/XDG in `tmp_path` and strips `DBUS_SESSION_BUS_ADDRESS`, `DISPLAY`, `GNOME_KEYRING_CONTROL` and similar variables. All 7 tests ran (none skipped).
- `~/.local/share/keyrings` listing (with mtimes) is identical before and after the full test run. No new `dbus-daemon` or `gnome-keyring-daemon` processes remain.

## Tests added
- `tests/unit/test_secrets_edge.py`:
  - timeout while the command's parent has exited but a background child keeps stdout open (**fails**, problem 1);
  - unbalanced quote in `cmd` → error without the command text;
  - non-zero exit code and program name in the message;
  - CRLF/trailing newlines trimmed, leading/inner whitespace kept;
  - output exactly at the limit is accepted, one byte over is an error;
  - `run_command` (value and timeout) on `GLibEventLoopPolicy`, the loop the app uses;
  - `resolve_env` keeps the error type and names the variable for keyring-unavailable and prompt-without-callback;
  - `resolve_env` with a mix of present and missing sources returns only the present ones;
  - redaction of a secret inside dict args and inside an exception traceback;
  - one record through two handlers with the same filter;
  - redaction length boundary (3 characters kept, 4 redacted).

## Problems (for the implementer; each actionable)
1. A timed-out `command` source leaves its child processes running when the parent process has already exited. Reproduce: `.venv/bin/pytest -q tests/unit/test_secrets_edge.py::test_timeout_when_parent_exits_but_child_keeps_stdout` (command `sh -c 'sleep 30 & echo $! > pidfile; exit 0'`, timeout 0.5 s). Expected: the timeout error, and the `sleep 30` child killed. Actual: the error is raised, but `sleep 30` keeps running. Cause: `app/secrets.py` `_kill()` calls `os.killpg` only when `proc.returncode is None`. The asyncio child watcher sets `returncode` as soon as `sh` exits, so the process group, which still has the background child, is never signalled. Fix: always `killpg(proc.pid, SIGKILL)` on timeout or error (keep suppressing `ProcessLookupError`/`PermissionError`). The group exists as long as any member is alive. This contradicts the report's claim "a timed-out command is killed together with its child processes", and the existing `test_command_timeout_kills_children` misses it because there the parent is still alive.

## Suggestions (non-blocking)
- `app/cli.py:21` `_SECRET_NAME_RE` uses `re.match` with `$`, so a name with one trailing newline (`"abc\n"`) is accepted. Use `fullmatch` or `\Z`.
- `resolve()` with a `prompt` callback that returns `""` puts an empty variable into the environment. `terminal_prompt` already maps `""` to `None`. Consider doing the same in `resolve()` so the GUI prompt behaves the same way.
