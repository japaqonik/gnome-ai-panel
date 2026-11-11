# Test report S1-T1 attempt 1
Verdict: PASS

## Command results
- `make setup` → 0 (Playwright prints a host-dependency warning for WebKit, which is not fatal)
- `make build` → 0 (schema and extension steps are skipped because `extension/` does not exist yet)
- `make lint` → 0 (ruff check, ruff format --check, ESLint `--max-warnings 0`)
- `make test` → 0: pytest 12/12 (7 from the implementer and 5 added by me), gjs `1 passed`, Playwright with no tests exits 0
- Stub targets `run`, `run-headless`, `stop`, `test-shell`, `cli`, `install`, `uninstall`, `vendor` → each prints `make <target>: not implemented yet` and exits 0

## Done-when criteria
- [x] `make setup` → exit 0. Evidence: `make setup; echo $?` → `0`.
- [x] Without `Xvfb` → exit 1 and prints `sudo apt install xvfb`. Evidence: `env PATH=<fake bin without Xvfb> /usr/bin/make setup` → stdout `sudo apt install xvfb`, stderr `brak: Xvfb`. `scripts/check-deps.sh` exits 1, so make stops and reports exit 2. GNU make always returns 2 when a recipe fails, so exit 1 at the `make` level cannot be produced. I count the criterion as met through the script's exit code. The pytest test `test_missing_xvfb_prints_apt_command` covers it.
- [x] `make lint` → 0.
- [x] `make test` → 0. pytest reports `12 passed`, the gjs runner prints exactly `1 passed`, and `playwright test --pass-with-no-tests` exits 0.
- [x] `git status --porcelain` shows nothing from `.venv/`, `node_modules/`, `__pycache__/`, `.run/` or `test-results/`. Evidence: the grep matched nothing (exit 1).
- [x] Tests: `test_version` checks that the version is a semver string. `sanity.test.js` runs `gjs` on a fixture with a deliberate failure and expects a non-zero exit.

## Exploratory checks
I added each of these temporarily and removed it afterwards:
- A failing pytest test makes `make test` exit 2. Failures propagate.
- A gjs test that throws makes `make test-gjs` fail. A gjs file with a syntax error is reported as `cannot load` and the runner exits 1.
- A failing Playwright spec makes `make test-ui` exit 2. `PW_BROWSER=bogus` makes it exit 2 with a clear message.
- A ruff violation (an unused import in `app/`) and an ESLint violation (`var` in `tests/gjs`) each make `make lint` exit 2.
- A passing Playwright spec under WebKit fails with "Host system is missing dependencies". The same spec under `PW_BROWSER=chromium` passes. See "System packages" below.
- No Xvfb or dbus processes were left running.

## Tests added
- `tests/unit/test_check_deps.py`:
  - `test_missing_tool_maps_to_apt_package`, parametrized over node→`nodejs`, npm→`npm`, gjs→`gjs`, glib-compile-schemas→`libglib2.0-bin`.
  - `test_missing_python3_does_not_crash`: without python3 the script prints `sudo apt install python3` and exits 1, and no "command not found" appears.
- `tests/gjs/sanity.test.js`: the existing test now also checks that a module throwing on import counts as a failure (`0 passed, 1 failed`, `cannot load`, exit ≠ 0). I extended the one existing test instead of adding a second, so the default run still prints `1 passed`.
- New fixture `tests/gjs/fixtures/throws-on-load.test.js`.

## Problems (for the implementer; each actionable)
None.

## System packages (sudo, needed later, not blocking S1-T1)
Playwright WebKit cannot start because the host is missing `libevent-2.1-7t64`, `libavif16` and `libmanette-0.2-0`. Install them with `sudo npx playwright install-deps webkit` or `sudo apt-get install libevent-2.1-7t64 libavif16 libmanette-0.2-0`. S1-T3 (`tests/ui/smoke.spec.mjs`) needs these packages, or else `PW_BROWSER=chromium`, which works now.

## Suggestions (non-blocking)
- README says `make setup` "stops with exit code 1" when something is missing. The script exits 1, but `make` itself exits 2. The README should say "non-zero", or name the script's exit code.
- `check-deps.sh` prints its diagnostics in Polish (`brak:`, `Brakuje pakietów…`), while the README and the rest of the output are in English. The language should be consistent.
- `Makefile` uses `npx --no-install`, which is good. `package.json` scripts call `eslint`/`playwright` without `--max-warnings 0`/`--no-install`. This is harmless because `make` is the canonical entry point.
