# Test report S4-T1 attempt 1
Verdict: PASS
## Command results
- build: `make build` exit 0
- lint: `make lint` exit 0 (ruff check, ruff format, ESLint; schema check skipped, no `extension/schemas` yet)
- test: `make test` exit 0. pytest 727/727, GJS 1/1, Playwright 75/75 (Chromium fallback: WebKit is missing `libevent-2.1.so.7` on this machine)
- After adding tester tests: pytest `tests/unit/test_controller_tools.py` 8/8, `make test-ui` 81/81, `make lint` exit 0

## Done-when criteria
- [x] `npx playwright test tests/ui/tools.spec.mjs` → passed. Evidence: `PW_BROWSER=chromium npx playwright test tests/ui/tools.spec.mjs` → 9 passed. A plain `npx playwright test …` uses the config default, WebKit, which cannot launch here because a host library is missing (`sudo npx playwright install-deps webkit`). This is an environment issue, not a code defect. `make test-ui` falls back to Chromium as documented.
- [x] headless + `fake-tool`: `debug-send "'x'"` → `ui-dump` `messages[-1].tools[0].status == "completed"`. Evidence: `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-tool make run-headless` (exit 0), `debug-send "'x'"`, `ui-dump` → `thinking: 'Sprawdzę plik.'`, `tools: [{id: call_1, title: 'Odczyt pliku notes.txt', status: completed}]`, `busy: false`. A second prompt added a second assistant message with its own card. `new-chat` cleared the list (0 messages). `make stop` exit 0, no leftover processes.
- [x] Listed tests exist and pass: Playwright `<details>` without `open`, `tool_call` + 2× `tool_update` → one `completed` card, `<script>` in `raw_input` shown as text, unknown `id` ignored. Controller unit test for event order: `test_thinking_and_tool_events_keep_their_order`.
- [x] UAT-S4-2 check (non-empty thinking and tool title) also holds in the same dump.

## Tests added
- tests/ui/tools-edge.spec.mjs (6 cases):
  - malformed events (missing, empty, numeric or 257-character ids; non-string or empty thinking) are ignored without page errors
  - `tool_update` with `null` fields keeps the title, status and input
  - every ACP status sets `data-status` and a label
  - thinking that arrives after a card and text still sits above the cards, the dump keeps it out of `text`, and the header ends as "Myślenie"
  - `<img onerror>` in tool output is sanitised and its script does not run
  - `conversation` clears the cards, and an update of the old id in the next turn is ignored
- tests/unit/test_controller_tools.py (2 cases):
  - interleaved thinking and tool events keep their order, and the thinking parts are joined
  - `ToolUpdate` without fields sends `{type, id}` and leaves the stored call unchanged

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
- `ToolUpdate` with no changed fields is still sent as `{type: "tool_update", id}`. This is harmless, but the controller could skip it.
- The change to `test_turn_dispatch_order` in `tests/unit/test_controller.py` replaces the S3 expectation that thinking is dropped. This follows the new requirement and does not weaken the test.
