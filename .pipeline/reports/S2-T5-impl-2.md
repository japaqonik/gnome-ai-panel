# Implementation report S2-T5 attempt 2

## Changes
- app/cli.py (`run_chat`): the turn is now consumed in its own task (`cli-chat-turn`). When
  `--cancel-after` is given, `run_chat` waits one loop step (`asyncio.sleep(0)`) before
  starting the cancel timer. By then `send()` has registered the turn, so `cancel()` takes
  effect even with a 0 s delay. On exit the consumer and timer tasks are cancelled and awaited,
  so Ctrl+C behaves as before.
- tests/fakes/fake_acp_agent.py: the per-session cancel flag is now cleared when
  `session/prompt` is read (in `handle()`), not when the prompt task starts. Before this change,
  a `session/cancel` that arrived in the same read as the prompt was set and then wiped by the
  starting prompt task. That is a race in the fake agent: per ACP, a cancel sent after a prompt
  applies to that prompt. With the CLI fix alone, `--cancel-after 0` still ended with `end_turn`
  without DEBUG logging, because both lines reached the fake agent together.
- tests/unit/test_cli_chat.py: added `LazyTurnBackend`, which registers its turn only once
  iteration starts and ignores `cancel()` when no turn is running (the same as `AcpBackend`).
  Added `test_run_chat_cancel_after_zero_cancels_running_turn`.

## Problems from previous report
- `--cancel-after 0` accepted but did nothing → fixed (CLI timer starts after the turn is
  registered; fake agent race fixed). Tester's `test_cancel_after_zero_cancels_immediately`
  passes. I ran it manually 5 times in a row and got `cancelled` every time.
- Non-blocking: an interrupted `--json` run has no final `done`/`error` line → not changed.
  Ctrl+C is reported by exit code 130, and the plan defines no JSON event for an interrupt.
  Adding one would be a new output format, so it should be decided in the plan.
- Non-blocking: `[options]` is not printed for `configOptions` from `session/new` → not
  changed. `Backend.new_session()` returns only the session ID, so the CLI cannot see them
  without changing the backend interface. That belongs to the later model/options task (the
  controller's `config_options`).
- Non-blocking: `~/.cache/gnome-ai-panel-fake/{echo,missing}` in the real home → left in place.
  The role forbids commands outside the project directory. The user can remove them with
  `rm -r ~/.cache/gnome-ai-panel-fake`. This time I ran all manual commands with a temporary
  `HOME`.
- Non-blocking: `app.log` mode 0664 → not changed. That file is created by
  `app/logging_setup.py` from an earlier task, so the change is outside S2-T5. I recommend
  creating it with 0600 in a fix task.

## How to verify
- `AI_PANEL_CONFIG=tests/data/config_fake.toml .venv/bin/python -m app.cli chat fake-slow x --json --cancel-after 0 | tail -1`
  → `{"type": "done", "stop_reason": "cancelled"}` within about 0.3 s, exit 0.
- `... chat fake-slow x --cancel-after 0.5` → a few fragments, then `[done] cancelled`, exit 0.
- `... chat fake-echo hi --cancel-after 30` → `Echo: hi`, exit 0.
- `.venv/bin/pytest tests/integration/test_cli_chat_signals.py tests/unit/test_cli_chat.py`

## Command results
- build: ok, lint: ok, test: pytest 572/572, gjs 1/1, Playwright 3/3 (Chromium fallback,
  WebKit host libraries missing). No fake agent processes left running.

## Known limitations / deviations from plan
- None beyond the non-blocking points above.
