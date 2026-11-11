# S1 git report 1

Mode: COMMIT, stage S1 "Szkielet aplikacji".

## Review
- UAT: `.pipeline/reports/S1-uat-1.md` → `Verdict: PASS`.
- Change set: 52 new files (app/, scripts/, tests/, Makefile, package.json + lock, pyproject.toml,
  requirements*.txt, eslint/playwright configs, README.md, .env.example, S1 reports) and 4 modified
  (.gitignore, .pipeline/STATE.md, .pipeline/TASKS.md, .pipeline/reports/S0-git-1.md, which got its
  Result section after the S0 commit).
- Runtime artefacts ignored and not staged: `.run/`, `.venv/`, `node_modules/`, `test-results/`,
  `.pytest_cache/`, `.ruff_cache/`, `.pipeline/uat-scripts/`. `.gitignore` already covered them
  (implementer added `.run/` and `*.compiled`); no change needed from me.
- Secrets: none. `.env.example` has empty values only; no real `.env`. Grep for key/token
  patterns found nothing.
- Debug leftovers: none. `console.log` in `scripts/pick-browser.mjs` is its stdout output;
  `print` in `tests/gjs/run.js` is the GJS runner's output. No TODO/FIXME.
- Skipped tests: only environment guards (`pytest.skip` when no display or a tool is missing);
  none triggered in the run below. `tests/gjs/fixtures/failing.test.js` and
  `throws-on-load.test.js` are fixtures for the runner self-test, not disabled tests.
- Scope: all changes belong to S1. Largest file is package-lock.json (40 KB).

## Commands
- `make test` → exit 0: pytest 86 passed; GJS 1 passed; Playwright 3 passed on Chromium
  (WebKit fallback: `libevent-2.1.so.7` missing on host, documented behaviour).
- `make lint` → exit 0 (schema check skipped, no schemas yet).
- `git add -A`, `git commit -F .pipeline/reports/S1-commitmsg.txt`, `git push origin main`.

## Result
- Commit: `05c4b37` `feat(s1): add application skeleton`
- Push: `git push origin main` → OK, `cdc7313..05c4b37  main -> main`.
- Note: this Result section was appended after the commit, so this file shows as modified
  locally and will go into the next stage commit.

Verdict: DONE
