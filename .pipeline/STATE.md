# Pipeline state
status: running
spec: /home/rpac/Dev/gnome-ai-panel/gnome-ai-panel.md
remote: https://github.com/japaqonik/gnome-ai-panel
current: S3-git
counters: test_loops=4 fix_cycles=0 git_rejects=0

## History
- 2026-11-10T21:35:28+01:00 planning started
- 2026-11-10T21:35:28+01:00 plan written (11 stages, 39 tasks), awaiting approval + remote URL
- 2026-11-10T22:38:42+01:00 plan approved; default shortcut changed to <Super>i (verified free); remote set
- 2026-11-10T22:45:00+01:00 S0 committed cdc7313 (chore: project plan)
- 2026-11-10T23:00:00+01:00 S1-T1 PASS (attempts: 1); note: Playwright WebKit host libs missing (sudo npx playwright install-deps webkit) - chromium works
- 2026-11-10T23:20:00+01:00 S1-T2 PASS (attempts: 1); asyncio on GLib loop works, plan B not needed; open: NFR-2 navigation blocking not scheduled in any task
- 2026-11-10T23:45:00+01:00 S1-T3 PASS (attempts: 1); notes: S3-T4 done-when uses `gapplication list-actions` (fails without .desktop until S6); /tmp/aip-wklibs leftover for manual removal
- 2026-11-11T16:50:20+01:00 resumed at S1-uat
- 2026-11-11T17:10:00+01:00 S1 UAT PASS (S1-uat-1); UAT-S1-4 [manual] needs visual confirmation by the user (no title bar, "Dodaj agenta")
- 2026-11-11T17:20:00+01:00 S1 committed 05c4b37 (feat(s1): add application skeleton), pushed to origin/main
- 2026-11-11T17:50:00+01:00 S2-T1 PASS (attempts: 1); notes: `make cli` exits 2 on failure (make limitation, CLI exits 1, documented); non-blocking: KEY substring match warns on e.g. MONKEY
- 2026-11-11T18:40:00+01:00 S2-T2 PASS (attempts: 2); fixed: timed-out command left children running; decision: keyring used only when Secret Service already runs on the bus (no D-Bus activation)
- 2026-11-11T19:40:00+01:00 S2-T3 PASS (attempts: 3); fixed: unencodable reply hang, deep-nesting RecursionError (parse + DEBUG log); open (non-blocking): `"id": NaN` request gets no reply; `make test-py` cleanup prints `rm: … doc: Jest katalogiem` and leaves /tmp runtime dir (Makefile, S1 code)
- 2026-11-11T20:20:00+01:00 S2-T4 PASS (attempts: 1); integration tests 5.95 s; non-blocking: MCP commands looked up in app PATH (not agent env PATH); send() after close() reports kind `crashed`
- 2026-11-11T21:10:00+01:00 S2-T5 PASS (attempts: 2); fixed: --cancel-after 0 race (CLI + fake agent); open (non-blocking): app.log created 0664 (logging_setup, S1); interrupted --json run has no final done line; configOptions from session/new not printed; leftover ~/.cache/gnome-ai-panel-fake in real HOME (user may remove)
- 2026-11-11T21:50:00+01:00 S2 UAT PASS (S2-uat-1); UAT-S2-5 passed with real kiro-cli 2.26.0; note: UAT wrote+deleted test-x item in user's real keyring (HOME isolation does not isolate keyring); 8 old /tmp/ai-panel-test-runtime.* dirs remain
- 2026-11-11T22:05:00+01:00 S2 committed fa15568 (feat(s2): add config loading and terminal ACP client), pushed to origin/main
- 2026-11-11T22:45:00+01:00 S3-T1 PASS (attempts: 1); deviation: highlight.js vendored from @highlightjs/cdn-assets@11.12.0 (npm, prebuilt); note for S3-T4: relative links also get data-external
- 2026-11-11T23:30:00+01:00 S3-T2 PASS (attempts: 1); contract for S3-T3: every `send` must get `done`/`error` (also when rejected), no `text_delta` after `done`, repeated `cancel` idempotent; a11y note: live region re-read per frame
- 2026-11-12T00:20:00+01:00 S3-T3 PASS (attempts: 1); tester fixed race in test helper process_gone() (test_acp_backend_edge.py); open: send() catches only NotImplementedError from backend factory; agent ignoring session/cancel never ends turn (S4-T3 timeout); _alive race in test_run_scripts.py
- 2026-11-12T01:15:00+01:00 S3-T4 PASS (attempts: 1); deviation: debug-action absence checked via gdbus org.gtk.Actions.List (list-actions needs .desktop, S6); dump has extra `busy`, `uri`; thinking/tools/permission_dialog/banner placeholders until S4; non-blocking: links.is_external accepts leading-space URI
- 2026-11-12T02:00:00+01:00 S3 UAT PASS (S3-uat-1); manual pending: UAT-S1-4 + visual check of chat on real desktop