# Implementation report S2-T2 attempt 1

## Changes
- `app/secrets.py` (new):
  - `SecretStore` Protocol with `ensure_available/get/set/delete/has`.
  - `MemoryStore` for tests.
  - `LibsecretStore`: GI `Secret-1`, schema `pl.local.AiPanel.Secret`, attribute `name`; `gi` is imported lazily. Before every call it checks `NameHasOwner("org.freedesktop.secrets")` on the session bus and raises `SecretServiceUnavailable` when there is no owner or no bus. This means the service is never D-Bus-activated: activation would start gnome-keyring with the bus's environment, and a private test bus could reach the real home that way.
  - `resolve(source, *, store, prompt_cb, name=None) -> str | None` handles all five sources:
    - `keyring` runs in `asyncio.to_thread`; a missing item gives `None`.
    - `env` gives `None` when the variable is unset.
    - `command` uses `shlex.split` and `create_subprocess_exec` (no shell), stdin is `/dev/null`, stderr is discarded, and it runs in its own process group so a timeout kills the whole group. Trailing `\r\n` is trimmed. The error names the program and the exit code, never stdout. stdout is limited to 1 MiB and must be UTF-8.
    - `prompt` calls the async callback; without a callback it raises `InteractionRequired` ("wymaga interakcji").
    - `literal` returns the value from the file.
  - `resolve_env(entry, *, store, prompt_cb) -> dict[str, str]` works for agents and MCP servers (anything with `.env`). A variable without a value is skipped with an INFO log that names the variable and the source kind. Errors are re-raised with the same type and the variable name added, never the value.
  - Values from keyring, command and prompt are always registered for log redaction. Env and literal values are registered when the variable name matches `KEY|TOKEN|SECRET|PASSWORD`.
- `app/logging_setup.py`: added the `SecretRedactor` filter (global `REDACTOR`, `register_secret()`). It replaces known values with `[redacted]` in the message, the args, exception text and stack info. Values shorter than 4 characters are not redacted. `setup_logging()` attaches the filter to the stderr and file handlers.
- `app/cli.py`:
  - New `secret set|delete|has NAME` commands. `set` reads the value from stdin (`getpass` on a TTY), at most 64 KiB, UTF-8, with trailing newlines trimmed; an empty value is an error. Exit codes are 0 on success and 1 on error, for a missing item, and for `has` when the item does not exist.
  - Errors are printed as `błąd: …` on stderr, with no traceback. Availability is checked before reading stdin. The store comes from `make_store()` so tests can replace it.
  - `terminal_prompt(label)` is the CLI `prompt_cb`: `getpass` on a TTY, otherwise `InteractionRequired`. S2-T5 will pass it to `resolve_env`.
- `app/strings.py`: Polish messages for secrets and the `secret` CLI.
- `pyproject.toml`: ruff `S105` ignored in `app/strings.py` and `tests/**`. It flagged message constants named `SECRET_*` as hard-coded passwords, which they are not.
- Tests (new):
  - `tests/unit/test_secrets.py` (35 cases):
    - each source;
    - `printf secret` → `secret`;
    - `false` → error with exit code and no value;
    - a failing command that printed the secret → secret not in `str`/`repr` of the error;
    - `sleep 20` with timeout 0.5 s → error in < 3 s, and child processes are killed;
    - missing program, non-UTF-8 output, output limit, empty command;
    - unset `env` → `None`;
    - prompt label, cancel, and no callback;
    - `resolve_env`: all sources, skipped optional variables (INFO log naming the variable, value absent), error naming the variable;
    - redaction: value absent from the captured log (message, args, exception) and from the real log file and stderr after `setup_logging()`; longest-first replacement, short values, bad format args;
    - importing `app.secrets` does not load `gi`.
  - `tests/unit/test_cli_secret.py` (19 cases): `set`/`has`/`delete` with `MemoryStore`, plus empty, too long and non-UTF-8 values, bad names, no service for every subcommand, and `terminal_prompt` with and without a TTY.
  - `tests/integration/test_libsecret.py` (7 cases) and `tests/integration/libsecret_probe.py`. Every test starts its own `dbus-daemon` with HOME/XDG in `tmp_path`, a fresh `XDG_RUNTIME_DIR` and no `DISPLAY`/keyring variables:
    - CLI without Secret Service (set/has/delete → 1, message, no traceback, service not activated on the bus);
    - CLI with a bus address that does not exist;
    - the Done-when command through `make -s cli` (make 2, CLI 1, message);
    - with a private unlocked `gnome-keyring-daemon` (keyring files in `tmp_path`): a `LibsecretStore` roundtrip that includes `resolve(Keyring)`, and the CLI `set/has/delete` roundtrip. These are skipped when the daemon is missing or does not start.
- `README.md`: added a value-sources table, the keyring commands, the "no Secret Service" behaviour and isolation of the keyring tests, and `secret` in the `make cli` row.

## Problems from previous report
- There is no previous report for S2-T2. The S2-T1 test report lists no problems.

## How to verify
- Without Secret Service on the bus:
  `printf 'abc' | env -i PATH=/usr/bin:/bin HOME=$(mktemp -d) dbus-run-session -- .venv/bin/python -m app.cli secret set test-x; echo $?`
  → `błąd: brak usługi Secret Service (keyring): usługa org.freedesktop.secrets nie działa; …` and `1`. Through `make cli` the same message appears and make exits 2. This is the GNU make convention, as in S2-T1.
- `.venv/bin/pytest -q tests/unit/test_secrets.py tests/unit/test_cli_secret.py tests/integration/test_libsecret.py` → 61 passed.
- `make test` → exit 0.

## Command results
- build: ok
- lint: ok
- test: pytest 277/277 passed; GJS passed; Playwright 3/3 (Chromium fallback, because WebKit is missing `libevent-2.1.so.7` on this host, same as before). `make test` exit 0.
- No keyring/dbus daemons were left running after the tests. The real `~/.local/share/keyrings` was not modified (mtimes unchanged).

## Known limitations / deviations from plan
- The plan says only "brak usługi Secret Service". The availability check (`NameHasOwner`) is stricter: an installed but not running gnome-keyring counts as unavailable. On a normal GNOME session the daemon is always running, so this changes nothing there. It prevents tests and headless runs from activating a keyring daemon.
- Values shorter than 4 characters are not redacted, because replacing every short string would make the log unreadable.
- `resolve_env` returns only the resolved entries. Merging with `os.environ` (PLAN §13) is the backend's job in S2-T4.
- The GUI `prompt_cb` (the `secret_prompt` bridge message) is not part of this task.
