# UAT report S2 attempt 1
Verdict: PASS

Environment: Ubuntu 26.04, working tree on top of 05c4b37 (S2 changes uncommitted). `make setup`,
`make build` and `make lint` ran first, all exit 0. The fake-agent checks ran with
`HOME`/`XDG_CONFIG|DATA|STATE|CACHE_HOME` pointing at a `mktemp -d /tmp/aip-uat-s2.XXXXXX`
directory (helper: `.pipeline/uat-scripts/s2env.sh`). Exact exit codes were checked with
`.venv/bin/python -m app.cli …`, as the README describes.

## Criteria
- UAT-S2-1: PASS. Ran `AI_PANEL_CONFIG=tests/data/config_fake.toml make cli ARGS="chat fake-echo 'Cześć' --json"`, exit 0. All 4 lines parse as JSON: three `{"type": "text_delta", …}` lines ("Echo: ", "Cz", "eść"), and the last line is `{"type": "done", "stop_reason": "end_turn"}`. The plain-text run prints `Echo: Cześć`, exit 0.
- UAT-S2-2: PASS. Ran the `test-agent` loop for fake-missing, fake-badver and fake-auth, through `make -s` and directly. Each run gives `rc=2` with no traceback, and each message is different:
  - `Nie znaleziono polecenia: /nonexistent/agent` plus a hint about the command/args/cwd/env fields;
  - `Nieobsługiwana wersja protokołu ACP: 99 (obsługiwana: 1)` plus a hint;
  - `Agent wymaga zalogowania. Dostępne metody: Fake login (Run `fake-agent login` in a terminal)…`.
- UAT-S2-3: PASS. `check-config --config tests/data/config_invalid.toml` prints `agents.broken.command: wymagane` plus 3 more path-prefixed errors and a summary line. The direct exit code is 1 (`make` reports 2, as documented). `agents --json` with the same file lists only `good` (`valid: true, default: true`), not `broken`, exit 0. On stderr it says `Pominięto błędnych agentów: broken (szczegóły: check-config).`
- UAT-S2-4: PASS. `chat fake-env SECRET_VAR` prints `s3cr3t-value`, exit 0. A second run with `AI_PANEL_LOG_LEVEL=DEBUG` was added. After both runs, `grep -r s3cr3t-value $XDG_STATE_HOME/gnome-ai-panel/` exits 1, and the DEBUG stderr has 0 matches. `app.log` contains `[redacted]`.
- UAT-S2-5 [manual]: PASS (run by the tester). `kiro-cli` is at `~/.local/bin/kiro-cli`. The test used a temporary config (`AI_PANEL_CONFIG`, `command="kiro-cli"`, `args=["acp"]`) with `cwd` set to a temp dir instead of `~/.cache/ai-panel` to avoid writing to the real home. Real HOME was kept so Kiro's login works, and `XDG_STATE_HOME` was temporary. `test-agent kiro` printed `Agent: Kiro CLI Agent 2.26.0`, `protokół: 1`, `OK: agent odpowiada i utworzył sesję.`, rc 0. `chat kiro 'Powiedz OK'` printed `OK`, rc 0. `~/.config` was not touched.

Additional user-style checks, all with readable output and no traceback:
- Unknown ID: exit 2 and the list of available IDs.
- Empty prompt: `Echo: `, exit 0.
- Missing arguments: argparse usage, exit 2.
- `fake-perm`: denied by default, with an `--permission allow` hint; with `--permission allow` it is allowed, and both exit 0.
- `fake-tool`: `[thinking]`/`[tool]` lines appear.
- `fake-slow --cancel-after 1`: 5 fragments, then `[done] cancelled`, exit 0.
- `fake-crash`: `błąd: Proces agenta zakończył działanie (kod 3)` plus stderr `boom`, exit 2.
- `fake-noise`: works.
- `type="api"` agent: `agenci typu „api” nie są jeszcze obsługiwani`, exit 2.
- A missing `cwd` (`~/…`) is expanded and created.
- `secret set` on a bus without Secret Service (`dbus-run-session`): `błąd: brak usługi Secret Service …`, exit 1.

## Regression (earlier stages)
- UAT-S1-1: PASS. `make setup`, `make lint` and `make test` each exit 0. pytest: 578 passed. GJS: 1 passed. Playwright: 3 passed on Chromium, using the documented WebKit fallback (missing `libevent-2.1.so.7`). Logs are in `.pipeline/uat-scripts/{setup,build,lint,test}.log`.
- UAT-S1-2: PASS. `make run-headless` printed `ui ready`. Toggling and calling `Describe` gave `[<true>]`, then `[<false>]`. `grep -c "ui ready"` on the headless log gave 8.
- UAT-S1-3: PASS. `make stop` exited 0 (stopped app, dbus-daemon, Xvfb). `pgrep -f "[p]ython -m app"` found nothing. A second `make stop` exited 0. The `/tmp/ai-panel-runtime.*` directory was removed.
- UAT-S1-4 [manual]: not run (needs a visual check on the user's desktop).

## Problems (for the implementer; each actionable)
None blocking.

## Observations (non-blocking)
1. Isolating HOME/XDG does not isolate the keyring: `secret set` uses the session bus from `DBUS_SESSION_BUS_ADDRESS`. During this UAT, `printf abc | python -m app.cli secret set test-x` wrote the item `test-x` into the user's real keyring. The tester deleted it right away with `secret delete test-x` and confirmed with `secret has test-x` (rc 1). This is expected behaviour. It would help if the README said that HOME/XDG overrides do not redirect the keyring (use `dbus-run-session` for that).
2. Eight leftover `/tmp/ai-panel-test-runtime.*` directories (each holding an empty `doc/`) remain from earlier `make test-py` runs, dated 17:21 to 18:30 on 2026-11-11. This UAT run did not add a new one. The tester did not remove them; they are safe to delete by hand.
3. `app.log` is created with mode 0664 (already noted in STATE).
4. A `test-agent fake-crash` run reports OK. This is correct, because the crash happens only after `session/prompt`.

## Needs human check
- UAT-S1-4: on the real GNOME session, run `make run && gapplication action pl.local.AiPanel show`, check that the window has no title bar and shows „Dodaj agenta”, then run `make stop`.
- UAT-S2-5 was run by the tester and passed. Optionally, repeat it with the literal `cwd = "~/.cache/ai-panel"` from the criterion.

Cleanup: all started processes were stopped (no `python -m app`, fake agents, Xvfb or `kiro-cli acp` remain). The temporary `/tmp/aip-*` files and directories were removed.
