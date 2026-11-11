# Test report S2-T1 attempt 1
Verdict: PASS

## Command results
- build: `make build` → exit 0
- lint: `make lint` → exit 0 (ruff check, ruff format --check, eslint; schema check skipped because `extension/schemas` does not exist yet). This includes my new test file.
- test: `make test` → exit 0. pytest 216/216 (181 from the implementer plus my 35), GJS passed, Playwright 3/3 on Chromium (WebKit fails with `libevent-2.1.so.7` missing, so the documented fallback is used, as in S1). No `/tmp/ai-panel-test-runtime.*` directory was left behind after my three runs.

## Done-when criteria
- [x] `AI_PANEL_CONFIG=/nonexistent make cli ARGS="agents --json"` → `[]`, code 0. Evidence: stdout `[]`, rc=0.
- [x] `make cli ARGS="check-config --config tests/data/config_invalid.toml"` → code 1 and a line starting with `agents.broken.command:`. Evidence: stdout starts with `agents.broken.command: wymagane`, followed by 3 more errors and a summary. `.venv/bin/python -m app.cli …` exits 1. `make` exits 2 (`make: *** [Makefile:88: cli] Błąd 1`), because GNU make always returns 2 when a recipe fails. I count this as met, following the S1-T1-test-1 precedent: the CLI exit code is 1, and the README documents how make reports it.
- [x] `make cli ARGS="check-config --config tests/data/config_valid.toml"` → code 0. Evidence: `Konfiguracja poprawna: …/config_valid.toml (agenci: 2, serwery MCP: 1).`, rc=0.
- [x] The tests the task requires are all in `tests/unit/test_config.py`: the SPEC §5.3 example (2 agents, 1 MCP, chat), missing file, empty file, syntax error giving one `ConfigError` with a line number, each kind of validation error (parametrized), empty `default_agent`, `~` expansion, the `literal` warning for `SOME_API_KEY` and none for `PLAIN_VALUE`, and the permission warning at `0666`.

## Tests added
- `tests/unit/test_config_edge.py` (35 cases, all pass):
  - `startup_timeout_s` set to `nan`, `inf`, `-inf`, `0`, `-1`, `600.5` or `true` is rejected and the agent is skipped. The boundaries `600`, `0.001` and `1` are accepted.
  - `chat.font_size` boundaries 5/6/72/73. A float font size is rejected and the default is kept.
  - A config path that is a directory gives one file-level error and `check-config` exits 1, with no traceback.
  - A literal secret value never appears in `check-config` or `agents` output (text and JSON), even when unknown keys and other errors surround it. It is not in `repr(Config)` either.
  - The `literal` warning also applies to `[mcp.x.env]` and is case-insensitive (`password`, `Db_Password`, `SECRET_X`, `akey`).
  - When one agent is invalid, `agents --json` still lists the valid ones and names the skipped one on stderr.
  - `default_agent = "  "` is treated as empty. The `default` flag in `agents --json` is set correctly.
  - Relative `command`, `cwd` and `args` resolve against the config file's directory even when the process cwd is `/`. Args like `--flag=./x` are left unchanged.
  - A relative `AI_PANEL_CONFIG` resolves against the process cwd.
  - The loader never creates the file or its parent directories, whether the path is explicit or the XDG default.
  - The syntax error line number matches the real line. The CLI prints it as `<file>:<line>: …`.
  - The Done-when commands run through `make -s cli` as a subprocess (exit 0, 2 and 0, plus the expected output).
  - `check-config` does not import GTK.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
- Matching `KEY` as a substring also warns for names like `MONKEY` or `KEYBOARD_LAYOUT`. This follows the task wording; anchoring on word boundaries or `_` could be considered later.
- `agents` exits 0 even when the file has errors (it only lists valid agents and reports skipped ones on stderr). This matches the "skip and keep working" rule. It could be worth stating in the README.
- The deviation on `width` is justified. SPEC §5.3 has no `width` key; `width` is a GSettings key (PLAN §12.5), so an unknown-key warning in `[chat]` is correct.
- Exploratory: `make run-headless`, `toggle` and `make stop` still work, and no app process was left running.
