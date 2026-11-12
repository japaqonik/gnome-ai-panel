# Implementation report S4-T1 attempt 1
## Changes
- app/controller.py (partial change from the interrupted attempt, reviewed and kept as is):
  `ThinkingDelta` → `thinking_delta {text}` (empty text skipped), `ToolCall` → `tool_call`
  (all fields), `ToolUpdate` → `tool_update {id, …}` with only the non-`None` fields; an update
  of an id the turn did not announce is dropped (debug log). The assistant message stores
  `thinking` and `tools: [{id, title, status, input, output}]` (PLAN §11.3), also when the turn
  ends with `error`. A missing tool status is stored as `pending`.
- app/ui/strings.js: strings from the previous attempt kept; added `toolTerminal`.
- app/ui/chat.js: handlers `thinking_delta`, `tool_call`, `tool_update`.
  - The thinking block is a `<details class="thinking">` placed before the tool cards and the body. It never gets
    `open`. Its summary shows "Myśli…" (`data-state="active"`) while thinking streams and
    "Myślenie" once text, a tool call, `done` or `error` arrives. The text is appended as a text node.
  - Tool cards are `.tools > article.tool[data-tool-id][data-status][data-kind]`, with
    the title (`textContent`, fallback "Narzędzie"), a status icon (CSS `::before` by
    `data-status`), a status label, a collapsible "Wejście" (`raw_input`: strings as they are, other values as indented
    JSON, via `textContent`) and a collapsible "Wynik" (ACP `content` blocks: text via
    `renderMarkdown` + `enhanceCodeBlocks`, `diff` as `<pre class="tool__diff">` with `-`/`+`
    lines, `terminal` as `<pre>` with its id, other block types as `[type]`).
  - A repeated `tool_call` id updates the same card. `tool_update` changes only the fields it carries, on
    the card of the current reply. Unknown ids, non-string ids, unknown statuses and
    updates after the turn ended are ignored.
  - The dump now fills `thinking` and `tools: [{id, title, status}]`. `text` and `html` now cover
    only the message body, without the thinking block and the tool cards.
- app/ui/style.css: styles for the thinking block, tool cards, status icons and output.
- tests/ui/tools.spec.mjs (new, 9 tests): collapsed `<details>` without `open` and the header
  switch; `tool_call` + 2× `tool_update` → one `completed` card, dump fields; `raw_input` and
  title containing `<script>`/`<img onerror>` shown as text; markdown output sanitised; diff as `<pre>`;
  unknown id/status ignored; order of several tools and repeated `tool_call`; defaults; no update
  after `done`.
- tests/unit/test_controller_tools.py (new, 6 tests): order of the events, stored message,
  unknown update dropped, repeated `tool_call`, empty thinking, tools kept on error, and a fresh
  tool set for each turn.
- tests/unit/test_controller.py: `test_turn_dispatch_order` now expects the `thinking_delta`
  that S3 dropped, plus `thinking` in the stored message (the behaviour this task asks for).
- tests/integration/test_debug_actions.py: new GUI test, `fake-tool` + `debug-send` → dump
  `thinking == "Sprawdzę plik."`, `tools == [{id: call_1, title: …, status: completed}]`.
- README.md: status paragraph, dump fields, and UI/controller description of the thinking blocks and tool cards.

## Problems from previous report
- No previous report exists for S4-T1. The partial diff (controller + strings) was correct, so
  I kept it and completed the UI, the tests and the README around it.

## How to verify
- `npx playwright test tests/ui/tools.spec.mjs` → 9 passed (here on Chromium via
  `PW_BROWSER=chromium`; WebKit cannot start on this machine because `libevent-2.1.so.7` is missing).
- `AI_PANEL_CONFIG=$PWD/tests/data/config_fake.toml AI_PANEL_DEFAULT_AGENT=fake-tool make run-headless && source .run/headless.env`,
  `gapplication action pl.local.AiPanel debug-send "'x'"`, `make -s cli ARGS="ui-dump"` →
  `messages[-1].thinking == "Sprawdzę plik."`, `messages[-1].tools[0].status == "completed"`
  (checked manually), then `make stop`.

## Command results
- build: ok, lint: ok, test: pytest 727/727, gjs 1/1, Playwright 75/75 (Chromium fallback)

## Known limitations / deviations from plan
- The plan's dump format lists tools as `{title, status}`. The dump also includes `id`, which costs
  nothing and lets tests match cards.
- Cards of a finished turn are frozen: a late `tool_update` after `done` is ignored (the
  controller never sends one anyway). S4-T3 will mark unfinished cards as `cancelled`.
- Stored `output` keeps the raw ACP `content` structure. It is not rendered when a conversation is
  reloaded, because history display comes in a later stage.
