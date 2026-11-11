# Test report S3-T2 attempt 1
Verdict: PASS

## Command results
- build: `make build` → exit 0
- lint: `make lint` → exit 0 (ruff, ruff format, ESLint with 0 warnings; schema check skipped, no `extension/schemas` yet). Still 0 with the new test file.
- test: `make test` → exit 0. pytest 578/578, GJS 1/1, Playwright 45/45 (Chromium fallback, WebKit cannot launch on this host). After adding `tests/ui/chat-edge.spec.mjs`: `make test-ui` → 58/58.

## Done-when criteria
- [x] `npx playwright test tests/ui/chat.spec.mjs` → passed. Evidence: `PW_BROWSER=chromium npx playwright test tests/ui/chat.spec.mjs` → 22 passed. The bare command (default `webkit`) fails on every test with `browserType.launch: Target page, context or browser has been closed`. That is the known missing host libraries (`libevent-2.1-7t64` etc., README), not a code defect, and the documented Chromium fallback applies.
- [x] `make test` → exit code 0 (see above).

## Tests listed in the task (each checked in chat.spec.mjs)
- Enter → bridge got `send`: "Enter sends the prompt…" asserts `[{type:'send', text}]`.
- Shift+Enter → newline, no `send`: value `a\nb`, `sent == []`.
- 50 `text_delta` → one assistant message with full text, and only 1 rAF requested.
- During a turn `#stop` visible, `#send` hidden, Enter does not send.
- Click stop → `cancel`.
- `done` restores `#send`.
- `error` shows the message, with `data-kind`, as text.
- `init` with empty agents → `#empty-state` visible, `#chat` hidden.

The implementer's tests assert behaviour (posted messages, DOM text, visibility, attributes) and also check for page errors in `afterEach`.

## Tests added
- `tests/ui/chat-edge.spec.mjs` (13 tests, all pass on Chromium):
  - `ready` is posted exactly once and `window.aiPanel` is frozen
  - before `init` the empty state is shown and the chat is hidden
  - two Enter keydowns in one task send only once
  - Enter during a turn leaves the draft unchanged (no newline added)
  - stop while the send is still pending (before `turn_start`) posts `cancel`
  - each turn gets its own assistant message
  - `error` outside a turn shows a bubble and the UI stays idle
  - `error` with no message and no kind gets a readable bubble labelled `unknown`
  - `max_tokens`/`refusal` markers are shown, and an unknown stop reason gets no marker
  - an HTML/XSS agent name in the header is shown as text
  - malformed `init.agents` (`[null, 'str', {id: 7}]`, non-array) does not throw
  - a new prompt can be sent after a cancelled turn
  - visible chat texts come from `strings.js`

## Exploratory checks
- `make run-headless` → `ui ready` in WebKitGTK, no errors in `.run/app.log`. `toggle` works. `make stop` cleaned up the processes and pid files.
- A `text_delta` that arrives after `done` starts a new assistant message and puts the UI back in the turn state (`#stop` visible). This follows the documented design ("a delta without `turn_start` also starts a reply"), so it is not a defect here. See suggestion 1.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
1. S3-T3: the controller must not send `text_delta` after `done`/`error`. If it does, for example a late chunk after a cancel, the UI stays in the turn state with no way out except another `done`. Another option is to ignore deltas when idle and no `turn_start` came.
2. Clicking stop several times posts several `cancel` messages. That is harmless, but the controller should treat repeated cancels as idempotent.
3. `#messages` is `role="log" aria-live="polite"`, and the assistant body is replaced through `innerHTML` on every frame. Screen readers may announce the reply again as it grows. Consider `aria-busy` (already set) plus announcing only on `done`, and check this with Orca later.
4. `chat.spec.mjs` cannot run on WebKit on this host. Before the release UAT, run it once on a machine that has `npx playwright install-deps webkit`.
