# Implementation report S2-T1 attempt 1

## Changes
- `app/config.py` (new): the configuration model from PLAN §11.1 as dataclasses: `Keyring`/`Env`/`Command`/`Prompt`/`Literal` (only parsed, not resolved; `Literal.value` is excluded from `repr`), `AcpAgent`, `ApiAgent`, `McpServer`, `ChatConfig`, `ConfigError(path, message, line=None)` and `Config` (`path`, `exists`, `default_agent`, `agents`, `mcp`, `chat`, `errors`, `warnings`, `skipped_agents`).
  - `config_path()`: `$AI_PANEL_CONFIG` (made absolute, `~` expanded) or `$XDG_CONFIG_HOME/gnome-ai-panel/config.toml`. A relative `XDG_*` value is ignored, as the XDG spec requires.
  - `load_config(path=None)` never raises for problems in the file:
    - A missing file gives an empty, valid config. Nothing is ever created.
    - An unreadable file, invalid UTF-8 or a TOML syntax error (tomlkit) gives exactly one file-level `ConfigError` (path `""`; `line` is set for syntax errors).
  - Validation covers:
    - required fields and types, including `bool` rejected as a number;
    - unknown agent `type` and unknown `source`;
    - required source fields: `name`, `cmd`, `value`;
    - `cmd` that `shlex` cannot split;
    - timeouts in the range (0, 600];
    - env variable names;
    - `mcp` references to a missing `[mcp.x]` or to an invalid one;
    - an unknown `default_agent`, and a `default_agent` that names a skipped agent;
    - API `endpoint` must be http(s), `max_tokens` must be ≥ 1, `models` items must be non-empty;
    - TOML dates inside `session_meta` (it is sent as JSON);
    - `[chat]`: `font_size` 6–72 and `theme` must be system/light/dark.
  - On errors, an invalid agent or MCP entry is skipped and the rest still loads. An invalid `[chat]` value keeps its default. Unknown keys only produce warnings.
  - Warnings:
    - a `literal` source whose variable name matches `KEY|TOKEN|SECRET|PASSWORD` (case-insensitive), including `api_key`;
    - a file that is group- or other-writable.
  - Path expansion: `~` and `$VARS` are expanded in `cwd`, `chat.history_dir`, in `command` when it contains `/`, and in `args` items starting with `~`, `./` or `../`. Relative paths are resolved against the directory of the config file. A bare `command` is left for the `PATH` lookup.
- `app/strings.py` (new): the Polish messages for the config and CLI code, kept in one place (NFR-8).
- `app/cli.py` (new): `python -m app.cli`, with no GTK import.
  - `check-config [--config P]` prints errors as `path: message`. File-level errors are printed as `file[:line]: message`. Warnings follow, prefixed with `ostrzeżenie: `, then a summary line. Exit code is 1 when there are errors, 0 otherwise.
  - `agents [--json]` lists only the valid agents (`id`, `type`, `name`, `valid`, `default`). Skipped agents are named on stderr.
- `Makefile`: `cli` runs `@$(PY) -m app.cli $(ARGS)`. The recipe is silent, so stdout carries only the CLI output, e.g. clean JSON.
- `tests/data/config_valid.toml` (the SPEC §5.3 example) and `tests/data/config_invalid.toml` (agent `good` is valid; agent `broken` lacks `command` and has a bad timeout, an unknown MCP reference and an unknown source).
- `tests/unit/test_config.py` (new, 83 tests) and `tests/unit/test_cli.py` (new, 12 tests).
- `README.md`: status line, new "Configuration" section, and a `make cli` row in the Development table.

## Problems from previous report
- There was no previous report for S2-T1.

## How to verify
- `AI_PANEL_CONFIG=/nonexistent make cli ARGS="agents --json"` prints `[]` with exit code 0.
- `make cli ARGS="check-config --config tests/data/config_invalid.toml"` prints `agents.broken.command: wymagane` among other lines. The CLI exits 1, which `make` reports as 2 (see limitations). `.venv/bin/python -m app.cli check-config --config tests/data/config_invalid.toml; echo $?` gives `1`.
- `make cli ARGS="check-config --config tests/data/config_valid.toml"` exits 0 with `Konfiguracja poprawna: … (agenci: 2, serwery MCP: 1).`
- `AI_PANEL_CONFIG=tests/data/config_invalid.toml make cli ARGS="agents --json"` lists `good` but not `broken`. stderr names `broken` as skipped.

## Command results
- build: ok
- lint: ok (ruff check, ruff format --check, eslint)
- test: ok. pytest 181/181, gjs all passed, Playwright 3/3 (Chromium fallback; WebKit is missing `libevent` on this host, as before).

## Known limitations / deviations from plan
- **Exit code through `make`:** GNU make always exits 2 when a recipe fails, so the Done-when line "`make cli … check-config …invalid…` → kod 1" can only be checked as "the CLI exits 1, make prints `Błąd 1` and exits 2". `.venv/bin/python -m app.cli …` returns the exact code. This is documented in README. Wrapping the recipe to always exit 0 would hide failures, so I did not.
- **`Config.warnings`:** this is a separate list next to `errors`. PLAN §11.1 lists only `errors`, but warnings must not count as failures.
- **`skipped_agents`:** added so that `default_agent` and `agents` can name the invalid entries.
- **`width` in the task scope:** this is a GSettings key of the extension (PLAN §12.5), not a `config.toml` key. In `[chat]` it is reported as an unknown key (warning). The ranges that are actually validated are `font_size` and the timeouts.
- **Unknown keys:** they are warnings, not errors, so a newer config file still loads.
- **Leftover temp dir:** one `make test-py` run left `/tmp/ai-panel-test-runtime.*` behind ("rm: … doc: Jest katalogiem", a race with the portal's FUSE mount; this comes from S1, not this task). I removed it by hand. The next run cleaned up normally.
