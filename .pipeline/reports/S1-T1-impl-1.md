# Implementation report S1-T1 attempt 1

## Changes
- `.gitignore`: extended (repo already existed, not re-initialised) with `.run/` and `*.compiled`; the other required entries were already present.
- `.env.example`: all variables from PLAN §13 (`AI_PANEL_CONFIG`, `AI_PANEL_LOG_LEVEL`, `AI_PANEL_DEBUG`, `AI_PANEL_DEFAULT_AGENT`, `AI_PANEL_URI_LOG`, `AI_PANEL_SKIP_EXTENSION_INSTALL`, `PW_BROWSER`) plus empty `ANTHROPIC_API_KEY=` with a note that it's an example for the `env` source.
- `Makefile`: every target from PLAN "Commands". `setup`, `build`, `lint`, `test`, `test-py`, `test-gjs`, `test-ui` work. `run`, `run-headless`, `stop`, `test-shell`, `cli`, `install`, `uninstall`, `vendor` print `make <target>: not implemented yet` and exit 0. `build` and `lint` skip the schema compile/check and the extension pack while `extension/` does not exist yet (S5-T1). ESLint runs with `--max-warnings 0`.
- `scripts/check-deps.sh`: checks `python3` (+ `venv`/`ensurepip`, `gi`, WebKit 6.0 GI), `Xvfb`, `xvfb-run`, `gjs`, `node`, `npm`, `glib-compile-schemas`. If anything is missing it prints `sudo apt install <packages>` (no duplicates) on stdout and exits 1.
- `pyproject.toml`: project version 0.1.0. ruff settings: line-length 100, py312, rules E/F/W/I/B/UP/S, with `.pipeline` and `*.md` excluded. pytest settings: `testpaths=["tests"]`, `pythonpath=["."]`, `asyncio_mode="auto"`, marker `gui`.
- `requirements.txt` (`httpx==0.28.1`, `tomlkit==0.13.3`) and `requirements-dev.txt` (`pytest==9.2.0`, `pytest-asyncio==1.4.1.post1`, `ruff==0.17.4`): exact pins.
- `package.json` + `package-lock.json`: exact devDependencies `marked 18.2.0`, `highlight.js 11.12.0`, `dompurify 3.4.17`, `@playwright/test 1.65.0`, `eslint 10.14.0`, `@eslint/js 10.0.1` (needed for the flat-config `recommended` preset), `globals 17.14.0`.
- `eslint.config.mjs`: browser globals for `app/ui`, GJS globals for `extension` and `tests/gjs`, node+browser globals for `tests/ui` and config files, and `app/ui/vendor` ignored.
- `playwright.config.mjs`: `testDir: tests/ui`, browser taken from `PW_BROWSER` (default `webkit`, invalid value → error).
- `app/__init__.py`: `__version__ = "0.1.0"`.
- `tests/conftest.py`: the `isolated_env` fixture points `HOME` and `XDG_CONFIG/DATA/STATE/CACHE_HOME` into `tmp_path` and removes `AI_PANEL_*` variables from the environment. Also adds a `repo_root` fixture.
- `tests/unit/test_version.py`: checks the version is a semver string and matches `pyproject.toml`.
- `tests/unit/test_isolated_env.py`: checks the fixture.
- `tests/unit/test_check_deps.py`: runs the script with a fake `PATH`. With everything present it exits 0. With Xvfb missing it exits 1 and prints `sudo apt install xvfb`. With several tools missing each package is listed once.
- `tests/gjs/run.js`, `tests/gjs/harness.js`: mini-runner. Without arguments it imports `tests/gjs/*.test.js`; it also accepts file paths as arguments. It prints `N passed` (or `N passed, M failed`) and calls `system.exit(1)` on failure. `test`/`assert`/`assertEqual` live in `harness.js`.
- `tests/gjs/sanity.test.js` + `tests/gjs/fixtures/failing.test.js`: runs the runner as a subprocess on a fixture with a deliberately failing test, expecting a non-zero exit and `1 passed, 1 failed`.
- `README.md`: purpose, system requirements with `sudo apt install …`, a commands table and notes on test isolation.

## Problems from previous report
- None. No `S1-T1-test-*.md` exists and no feedback was attached.

## How to verify
- `make setup; echo $?` → `0`. Playwright prints a host-dependency warning but does not fail.
- `make lint; echo $?` → `0`
- `make test; echo $?` → `0`. pytest shows `7 passed`, gjs shows `1 passed`, Playwright with no tests exits 0.
- `.venv/bin/pytest -q tests/unit/test_check_deps.py` covers the "no Xvfb → exit 1 + `sudo apt install xvfb`" case without uninstalling anything.
- `gjs -m tests/gjs/run.js tests/gjs/fixtures/failing.test.js; echo $?` → `1 passed, 1 failed`, `1`
- `git status --porcelain | grep -E '\.venv|node_modules'` → no output

## Command results
- setup: ok, build: ok, lint: ok, test: 8/8 (pytest 7/7, gjs 1/1, Playwright 0 tests, exit 0)

## Known limitations / deviations from plan
- System packages: `gir1.2-webkit-6.0`, `xvfb` and `xvfb-run` are now installed (PLAN §1 listed them as missing). `check-deps.sh` passes.
- Playwright WebKit host libraries are missing: `libevent-2.1-7t64`, `libavif16`, `libmanette-0.2-0`. Install them with `sudo npx playwright install-deps webkit` or `sudo apt-get install libevent-2.1-7t64 libavif16 libmanette-0.2-0`. They don't block S1-T1 because there are no UI tests yet, but S1-T3 (`tests/ui/smoke.spec.mjs`) needs them, or `PW_BROWSER=chromium`.
- `libsecret-tools` (`secret-tool`) was not checked by `check-deps.sh`, because PLAN "Commands" does not list it for `setup`. It is mentioned in the README.
- `tomlkit` is pinned to 0.13.3 following PLAN §8 (`0.13.*`), although 0.15.2 is available.
- ruff excludes `*.md` and `.pipeline/`. `ruff format` 0.17 formats Python code blocks inside Markdown and had modified `.pipeline/SPEC.md` and `gnome-ai-panel.md`. Both files were restored from HEAD and are unchanged.
- `make build`/`make lint` skip the schema and extension steps until `extension/` exists. S5-T1 will activate them automatically.
- Nothing was committed. No background processes are left running.
