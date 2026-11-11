# Implementation report S3-T2 attempt 1
## Changes
- `app/ui/chat.js` (new): `window.aiPanelChat.create({post})` returns `{dispatch}`. Chat screen logic:
  - Enter (without Shift, not during IME composition) sends `{type:"send", text}`. The text is sent as typed. A prompt that is empty or whitespace-only is not sent. Shift+Enter inserts a newline. The form submit (the `#send` click) uses the same path.
  - The user message is added locally as `textContent` (`white-space: pre-wrap`). The field is cleared and shrunk back.
  - Turn state: `send` → busy right away, so a double Enter cannot send twice before `turn_start` arrives. While busy, `#stop` is shown and `#send` is hidden. Enter is swallowed and does not send, and the draft stays in the field. `#messages` gets `aria-busy="true"`. A click on stop posts `{type:"cancel"}`.
  - `init {agents, current}`: an empty list shows `#empty-state`. Otherwise the chat screen is shown, with the name of the current agent in the header (falls back to the first agent, then to its id), and the prompt is focused.
  - `turn_start` creates the assistant message. `text_delta {text}` appends to a buffer and schedules at most one `requestAnimationFrame` render (`renderMarkdown` + `enhanceCodeBlocks`). A delta without `turn_start` also starts a reply.
  - `done {stop_reason}` flushes the buffer synchronously and restores `#send`. For `cancelled` it adds `<p class="message__status" data-status="cancelled">Przerwano</p>`, creating an empty assistant message if nothing was streamed. `max_tokens`, `max_turn_requests` and `refusal` get their own markers. A `done` outside a turn is ignored.
  - `error {message, kind}`: flushes the partial reply, adds a `.message--error` bubble (`role="alert"`, `data-kind`, message as text) and ends the turn. A `kind` that does not match `^[a-z][a-z0-9_]{0,31}$` becomes `unknown`.
  - Scrolling: the list follows new content while the user is within 24 px of the bottom. Scrolling up stops the following, and scrolling back to the bottom resumes it. Sending a prompt always jumps to the bottom.
  - The prompt grows with its content up to 8 lines, computed from the computed `line-height`, padding and border, then scrolls (`overflow-y: auto`).
  - `dispatch` returns `false` for non-objects, a missing or non-string `type`, and unknown types (later events such as `tool_call`).
- `app/ui/app.js`: creates the chat and exposes `window.aiPanel.dispatch` before posting `ready`.
- `app/ui/index.html`: loads `chat.js` and adds `#chat` (hidden by default): a header with `#agent-name`, `#messages` (`role="log"`, `aria-live="polite"`), and the form `#composer` with `textarea#prompt`, `#send` and `#stop`. `#empty-state` stays the initial screen, so the smoke test and `test_bridge.py` still hold until `init` arrives.
- `app/ui/strings.js`: labels, placeholder, button texts and the stop-reason markers (NFR-8). `chat.js` sets every visible text from here.
- `app/ui/style.css`: layout of the header, message list, bubbles (user, assistant, error), status marker, composer and danger button. Also `[hidden] { display: none !important }`, because `.empty-state { display: flex }` would otherwise override `hidden`.
- `tests/ui/chat.spec.mjs` (new, 22 tests): every case listed in the task, plus the send button, an empty prompt, IME-safe Shift+Enter, user text not parsed as HTML, the rAF count (50 deltas in one task request 1 frame), markdown/table/hljs/XSS in a streamed reply, `done` flushing without waiting for a frame, cancel before any delta, `done` outside a turn, an unsafe error kind, malformed events, prompt growth capped at 8 lines, and sticky scrolling.
- `README.md`: a paragraph on `chat.js` and the dispatch events.

## Problems from previous report
- None. No earlier S3-T2 report exists. S3-T1-test-1 had no problems. Its suggestion 3 (relative links get `data-external`) belongs to S3-T4.

## How to verify
- `PW_BROWSER=chromium npx playwright test tests/ui/chat.spec.mjs` → 22 passed. On a host with the WebKit libraries, run it without `PW_BROWSER`.
- `make test` → exit 0.
- `make run-headless` → `ui ready` in the log, which shows that `chat.js` loads in WebKitGTK under the CSP. Then run `make stop`.

## Command results
- build: ok, lint: ok, test: pytest 578/578, gjs 1/1, Playwright 45/45 (Chromium fallback; WebKit is missing `libevent-2.1.so.7` on this host).

## Known limitations / deviations from plan
- `init.theme`, `font_size`, `strings` and `config_errors` are not used yet (theme and font size belong to S3-T4, the config banner comes later).
- The busy state starts on the local `send`, not only on `turn_start`. If Python never answers, the UI stays busy until `done` or `error`. S3-T3 must answer every `send` with `turn_start`… `done`, or with `error` (also when it rejects a send during a turn).
- `requestAnimationFrame` does not fire while the WebView is hidden, so streamed text is painted when the panel is shown. `done` and `error` flush synchronously, so the DOM is complete once a turn ends (relevant for `ui-dump` in S3-T4).
- The running app still shows `#empty-state`, because Python sends no `init` until S3-T3.
