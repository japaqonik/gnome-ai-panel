# Implementation report S2-T4 attempt 1
## Changes
- `app/backends/acp.py` (new): `AcpBackend(agent, mcp_servers, *, store, prompt_cb)`.
  - Start: the process starts lazily on `start()` or `new_session()`. It runs `asyncio.create_subprocess_exec(command, *args)` without a shell and in its own process group. The environment is `os.environ` plus `resolve_env(agent)`. `cwd` is made absolute and created with mode 0700. A bare command is looked up in `PATH` of the agent environment; if it is missing, the error is `Error(kind="spawn", "Nie znaleziono polecenia: …")`.
  - `initialize` sends `protocolVersion: 1`, `clientCapabilities {fs:{readTextFile:false, writeTextFile:false}, terminal:false}` and `clientInfo`, with the `startup_timeout_s` timeout (kind `timeout`, the process is killed). Any version other than 1 gives kind `protocol`. `agentInfo`, `agentCapabilities` and `authMethods` are stored as attributes for S2-T5 `test-agent`.
  - `new_session()` sends `session/new` with the absolute `cwd` and `mcpServers` built from the agent's `mcp` list (`{name, command, args, env:[{name,value}]}`, with MCP env resolved through `resolve_env`). `session_meta` goes in as `_meta`. `systemPrompt {mode:"append", content:[text]}` is added only when `agentCapabilities.sessionCapabilities.systemPrompt` is advertised. This shape follows the ACP RFD "Client-Provided System Prompt", which reached Completed on 2026-11-06. An `auth_required` error (-32000 or the `auth_required` text) gives kind `auth`, `auth_methods` and a message listing the methods with a hint to log in from a terminal.
  - `send()` runs `session/prompt` as a task. `session/update` notifications are routed by `sessionId` into the turn's queue and mapped by `map_session_update`: `agent_message_chunk`→TextDelta, `agent_thought_chunk`→ThinkingDelta, `tool_call`→ToolCall, `tool_call_update`→ToolUpdate, `config_option_update`→ConfigOptions, `usage_update`→Usage. Everything else is ignored. The iterator ends with `Done(stopReason)` or `Error`. If the consumer closes the iterator early, the backend sends `session/cancel`.
  - `session/request_permission` becomes a `PermissionRequest(request_id="perm-N", …)` and waits for `respond_permission`. With `None` or an unknown option id, the backend picks the agent's `reject_once`/`reject_always` option, or answers `cancelled` if the agent offered no reject option. `cancel()` sends `session/cancel` and answers pending permissions of that session with `cancelled`. `fs/*`, `terminal/*` and other client methods get -32601.
  - Crash: if the process exits during a turn, the turn yields `Error(kind="crashed")` with the exit code (or signal) and the last 20 stderr lines (also in `Error.stderr`). Sessions of the dead process are marked lost. The next `new_session()` restarts the process, at most 3 restarts per 60 s (`RESTART_LIMIT`, `RESTART_WINDOW_S`); after that it raises kind `crashed` ("zbyt często").
  - `close()` sends SIGTERM to the process group, waits 3 s, then sends SIGKILL. It ends running turns and is safe to call twice.
  - `reconfigure()`: when the configuration changes, the process restarts at the next `new_session()`. A running turn is not interrupted (PLAN §4).
- `app/backends/__init__.py`: registry `get_backend(agent_cfg, *, mcp, store, prompt_cb)` keeping one backend per agent id, and `close_all()`. API agents raise `NotImplementedError` because they arrive in S7.
- `app/backends/base.py`: `Error` gained the optional fields `auth_methods` and `stderr`. Their defaults are `None`, so existing calls and `event_to_dict` still work. New exception `BackendError(event)` is used by `new_session`/`start`/`set_option`.
- `app/strings.py`: Polish messages `ACP_*`.
- `tests/fakes/fake_acp_agent.py`: new flag `--system-prompt` that advertises `sessionCapabilities.systemPrompt`, so the system prompt path can be tested.
- `tests/integration/test_acp_backend.py` (new, 41 tests, about 6 s): all scenarios listed in the task, plus the reject variants (`None`, unknown option), cancel with an open permission request, early close of the stream, two parallel slow sessions, a second turn in a busy session, a non-executable command, an agent exiting at start (stderr in the message), a failing secret command, the restart limit and its time window, SIGKILL of an agent that ignores SIGTERM, close during a turn, MCP env redacted in the DEBUG log, and the registry (one process per agent, restart after a config change).
- `tests/unit/test_acp_mapping.py` (new, 25 tests): the mapping, permission option parsing, the reject outcome, auth error detection, refusal of fs/terminal requests.
- `README.md`: the status paragraph now mentions the ACP client.

## Problems from previous report
- None: this is the first attempt and no S2-T4 report existed.

## How to verify
- `.venv/bin/pytest -q tests/integration/test_acp_backend.py tests/unit/test_acp_mapping.py` → 66 passed (about 6 s)
- `make test` → exit 0
- No leftover processes: `pgrep -af fake_acp_agent` shows nothing after the tests.

## Command results
- build: ok, lint: ok, test: 459/459 (test-py), 1/1 (test-gjs), 3/3 (test-ui; Chromium fallback because Playwright WebKit lacks `libevent-2.1.so.7`)

## Known limitations / deviations from plan
- `new_session()` raises `BackendError` (it carries the `Error` event) instead of returning an error, because the Backend protocol returns `str`. `send()` never raises; it yields `Error`.
- A `prompt` value source needs a `prompt_cb`; without one, starting fails with kind `spawn` ("wymaga interakcji"). The CLI or UI will pass a callback in S2-T5 and S8.
- `get_backend` uses `LibsecretStore` when no store is given. It is only used by `keyring` sources, and only when the Secret Service is already running.
- MCP server commands without `/` are resolved through the app's `PATH` before they are sent to the agent. If they are not found, they are sent unchanged.
- I also checked the backend by hand on `GLibEventLoop` (crash-once followed by echo); it works the same as on the default loop.
