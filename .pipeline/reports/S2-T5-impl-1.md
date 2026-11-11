# Implementation report S2-T5 attempt 1

## Changes
- `app/diagnostics.py` (new): `test_agent(cfg, *, mcp, store, prompt_cb) -> TestResult(ok, agent_info, protocol_version, auth_methods, error)`. Starts a private `AcpBackend` (not the shared `get_backend` registry, so a running conversation is never disturbed), runs `start()` (spawn + `initialize`) and `new_session()`, always `close()`s. Never raises for agent problems; unexpected exceptions become `Error(kind="other")`. `describe_agent(info)` ("Title (name) version") and `describe_error(error)` (message + Polish hint per kind: spawn/timeout/protocol/crashed; auth already carries the methods and a hint). API agents → `TestResult(ok=False)` "not available yet".
- `app/cli.py`: new commands
  - `chat ID PROMPT [--json] [--permission deny|allow] [--cancel-after S]`: `get_backend` → `new_session` → `send`, `close_all()` in `finally`. `TextPrinter` streams text live; `[thinking]` (per line), `[tool]`, `[permission]` (request with options + the answer, default "odrzucono (domyślnie; --permission allow zezwala)"), `[usage]`, `[options]`, `[done] <reason>` for stop reasons other than `end_turn`; errors to stderr as `błąd: …`. `JsonPrinter`: one `event_to_dict` object per line (`ensure_ascii=False`), plus `{"type":"permission_response","request_id","option_id","allowed"}` after every answer; last line is `done` or `error`. `--permission allow` picks `allow_once` (then `allow_always`); otherwise `respond_permission(id, None)` (backend picks the reject option). `--cancel-after` validated (finite, ≥ 0) and calls `backend.cancel()` after S seconds.
  - `test-agent ID`: prints `Agent: …`, `protokół: 1`, `metody logowania: …`, then `OK: …` or `Test połączenia nie powiódł się: <message>\n<hint>`.
  - Exit codes: 0 = `Done` / test ok, 2 = `Error`, failed test, unknown ID (stderr lists `Dostępni agenci: …`), skipped (invalid) agent, `api` type; 130 = Ctrl+C.
  - Both set up logging (file as the app; stderr handler only ERROR unless `AI_PANEL_LOG_LEVEL` is set) and use `terminal_prompt` for `prompt` sources.
- `app/logging_setup.py`: `setup_logging(stderr_level=None)` optional stderr threshold (default behaviour unchanged).
- `app/strings.py`: Polish CLI texts (`CLI_*`) and `DIAG_*` hints.
- `tests/data/config_fake.toml` (new): `default_agent = "fake-echo"`, one agent per scenario (`fake-echo … fake-env`, `fake-perm` → scenario `permission`, `fake-badver` → `bad-version`), `fake-env` with `SECRET_VAR = {source="command", cmd="printf s3cr3t-value"}`, `fake-missing` with `/nonexistent/agent`. Paths relative to the file (`../../.venv/bin/python`, `../fakes/fake_acp_agent.py`); `cwd = ~/.cache/gnome-ai-panel-fake/<scenario>`. Mode 0644 (no permission warning).
- `tests/unit/test_cli_chat.py` (new, 42 tests): permission choice, `seconds`, parser, `TextPrinter`/`JsonPrinter` output, `run_chat` with a scripted backend (exit codes, deny default, allow), `diagnostics.test_agent` against the fake agent (ok, missing command, bad version, auth keeps initialize info, timeout, api type, unexpected exception).
- `tests/integration/test_cli_chat_process.py` (new, 44 tests): CLI as a subprocess with `config_fake.toml`: every agent in text and `--json` mode (each line valid JSON, last line `done`/`end_turn` or `error`), deny default + explicit deny/allow, `--cancel-after 0.5` on `fake-slow` → `cancelled`, bad `--cancel-after` values, `fake-env` secret reaches agent but not the log (DEBUG), unknown ID → 2 + agent list (both commands), skipped agent, api agent, `test-agent` ok / three distinct failure messages / auth methods, no agent process left after `test-agent`. (Named `_process` because pytest has no package `__init__` and the basename clashed with the unit file.)
- `README.md`: status line, new "Chatting from the terminal" section, `make cli` row.

## Problems from previous report
- None: no earlier S2-T5 report and no feedback attached.

## How to verify
- `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-echo 'Cześć'"` → `Echo: Cześć`, exit 0
- `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="test-agent fake-echo"` → `Agent: Fake ACP Agent (fake-acp-agent) 1.0.0`, `protokół: 1`, exit 0
- `AI_PANEL_CONFIG=tests/data/config_fake.toml .venv/bin/python -m app.cli test-agent fake-missing; echo $?` → `Test połączenia nie powiódł się: Nie znaleziono polecenia: /nonexistent/agent` + hint, `2` (via `make`: make's own exit 2)
- `for a in fake-missing fake-badver fake-auth; do AI_PANEL_CONFIG=tests/data/config_fake.toml .venv/bin/python -m app.cli test-agent $a; echo rc=$?; done` → three different messages, `rc=2` ×3, no tracebacks
- `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-echo 'Cześć' --json"` → 3× `{"type": "text_delta", …}`, last `{"type": "done", "stop_reason": "end_turn"}`
- `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-slow x --cancel-after 0.5 --json"` → last line `{"type": "done", "stop_reason": "cancelled"}` after ~0.8 s
- `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-env SECRET_VAR"` → `s3cr3t-value`; the log does not contain it
- `.venv/bin/python -m app.cli chat nope x; echo $?` → `błąd: nieznany agent „nope”.`, `Dostępni agenci: …`, `2`

## Command results
- build: ok, lint: ok, test: pytest 554/554 passed, gjs 1/1, Playwright 3/3 (Chromium fallback: WebKit host libraries missing, pre-existing)

## Known limitations / deviations from plan
- `chat` and `test-agent` for `type = "api"` agents exit 2 with "nie są jeszcze obsługiwani" (ApiBackend is S7).
- A turn ending with `Done("cancelled")` (`--cancel-after`) is exit 0, matching PLAN §12.3 "0 Done / 2 Error".
- `fake-crash` passes `test-agent` (it only crashes after `session/prompt`); `chat fake-crash` exits 2 with the exit code and `boom` from stderr.
- `fake-crash-once`: its marker lives in `~/.cache/gnome-ai-panel-fake/crash-once`, so only the first chat after removing the marker crashes (documented in README).
- Running the fake config outside tests creates `~/.cache/gnome-ai-panel-fake/<scenario>` directories in the real home (as the task specifies `cwd` under the cache); tests use `isolated_env`.
