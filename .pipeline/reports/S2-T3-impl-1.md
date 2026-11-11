# Implementation report S2-T3 attempt 1
## Changes
- `app/backends/__init__.py`: new package (empty; `get_backend` registry belongs to S2-T4).
- `app/backends/base.py`: event dataclasses from PLAN §11.2 (`TextDelta`, `ThinkingDelta`, `ToolCall`, `ToolUpdate`, `PermissionOption`, `PermissionRequest`, `ConfigOptions`, `Usage`, `Done`, `Error` with `kind`), each with a `TYPE` matching the bridge names in §12.2; `event_to_dict()` for the bridge and `chat --json`; `Backend` runtime-checkable Protocol; `ContentPart` alias.
- `app/backends/jsonrpc.py`: `JsonRpcConnection(reader, writer)`:
  - `request()` uses integer ids, correlates responses in any order and accepts an optional `timeout`. An error response raises `JsonRpcError(code, message, data)`.
  - `notify()` sends notifications.
  - Incoming requests run in their own tasks, so a slow permission handler does not block the stream. The handler's result is sent back; a raised `JsonRpcError` is sent as the error, and any other exception becomes `-32603` without its text. With no handler the reply is `-32601`.
  - Notifications are handled in the reader loop, in order and before any later response.
  - Its own line splitter has a 16 MiB limit. A longer line closes the connection, because the message cannot be recovered after it.
  - Non-JSON and non-object lines are skipped with a DEBUG log. CRLF is accepted.
  - On EOF, a read or write error, or `close()`, every pending request fails with `ConnectionClosed(reason)` and running handlers are cancelled.
  - Traffic is logged at DEBUG only, shortened to 4096 characters, and `redact()` replaces every `env`/`headers` value (any case, recursively). The wire still carries the real values.
- `tests/fakes/fake_acp_agent.py`: stand-alone stdlib fake agent with all PLAN scenarios: `echo` (3 fragments, `md:` markdown), `thinking`, `tool`, `permission`, `slow`, `crash`, `crash-once` (marker in the session `cwd`), `bad-version`, `auth`, `noise`, `models`, `load`, `usage`, `image`, `env`. `--record` writes JSON Lines with the params of `initialize`/`session/new`/`session/load`/`session/prompt`. On stdin EOF it waits up to 2 s for running turns, so the `printf | …` check works. Executable.
- `tests/unit/test_jsonrpc.py` (28 tests): every case from the task "Tests" line plus extra ones:
  - all required cases: out-of-order responses, error → exception with code, incoming request → response, `garbage` skipped, 1 MiB line, EOF → `ConnectionClosed`, `env` redaction in the log;
  - error handling: handler errors, missing handler, malformed error object, broken writer, timeout with a late response;
  - streaming: byte-by-byte split, CRLF, line over the limit (with and without a newline);
  - ordering: notification order, a slow handler that does not block, two connections talking to each other;
  - logging: nothing logged above DEBUG.
- `tests/unit/test_backend_events.py`: event type names, JSON form, Protocol check.
- `tests/integration/test_fake_acp_agent.py` (24 tests): the Done-when `printf` command and every scenario through `JsonRpcConnection` over real subprocess pipes. Also covers two parallel sessions with correct routing, `--record` content, an unknown method or session, and exit on stdin EOF.
- `README.md`: Development section describes the fake agent and how to try it.

## Problems from previous report
- No previous report for S2-T3.

## How to verify
- `printf '%s\n' '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}' | .venv/bin/python tests/fakes/fake_acp_agent.py --scenario echo` → one JSON line containing `"protocolVersion": 1`, exit 0.
- `.venv/bin/pytest -q tests/unit/test_jsonrpc.py tests/unit/test_backend_events.py tests/integration/test_fake_acp_agent.py` → 56 passed (~3 s).
- `make test` → exit 0.

## Command results
- build: ok, lint: ok, test: test-py 355/355 passed, test-gjs 1/1, test-ui 3/3 (Chromium fallback, because Playwright WebKit lacks `libevent-2.1-7t64` on this machine).

## Known limitations / deviations from plan
- `JsonRpcConnection.close()` does not close the writer or the process. Process lifecycle (SIGTERM/SIGKILL) is AcpBackend's job (S2-T4).
- Notification handlers are awaited inline to keep `session/update` ordered relative to the `session/prompt` response, so they must be quick. Request handlers run concurrently.
- Fake `auth` sends `{"reason": "auth_required"}` as error `data` with code `-32000`, the ACP convention. `slow` checks cancellation every 200 ms, so a cancel takes ≤ 0.2 s.
