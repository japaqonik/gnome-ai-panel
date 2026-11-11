# Implementation report S2-T2 attempt 2
## Changes
- app/secrets.py: `_kill()` now always calls `os.killpg(proc.pid, SIGKILL)` (still ignoring
  `ProcessLookupError` and `PermissionError`), so on timeout, output overflow or cancellation
  the whole process group dies even when its leader has already exited. The group id cannot be
  reused while any member of the group is alive, so this does not hit unrelated processes.
- app/secrets.py: in `resolve()`, an empty answer from the prompt callback is treated as
  `None` (no value, variable skipped), the same as `terminal_prompt`.
- app/cli.py: `_SECRET_NAME_RE` is used with `fullmatch` (pattern without `^`/`$`), so a name
  with a trailing newline is rejected.
- tests/unit/test_secrets.py: `test_prompt_empty_answer_is_none` (resolve and resolve_env).
- tests/unit/test_cli_secret.py: `"trailing\n"` added to the `test_bad_name` cases.

## Problems from previous report
- Timed-out command leaves children running → fixed in `_kill()` as described;
  `tests/unit/test_secrets_edge.py::test_timeout_when_parent_exits_but_child_keeps_stdout` passes.
- (suggestion) secret name with a trailing newline accepted → fixed with `fullmatch`, test added.
- (suggestion) empty prompt answer put into the environment → now `None`, test added.

## How to verify
- `.venv/bin/pytest -q tests/unit/test_secrets_edge.py` → 12 passed
- `.venv/bin/pytest -q tests/unit/test_secrets.py tests/unit/test_cli_secret.py` → all pass
- `make test` → exit 0; afterwards `pgrep -af 'sleep 30'` shows nothing.

## Command results
- build: ok, lint: ok, test: pytest 291/291, GJS 1/1, Playwright 3/3 (Chromium fallback,
  WebKit host libraries missing)

## Known limitations / deviations from plan
- After a command finishes successfully, background children it left behind are not killed
  (only the timeout and error paths kill the group). A child that keeps stdout open makes the
  read block, so that case ends in the timeout path and is killed.
