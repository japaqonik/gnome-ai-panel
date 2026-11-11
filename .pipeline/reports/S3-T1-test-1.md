# Test report S3-T1 attempt 1
Verdict: PASS

## Command results
- build: `make build` exit 0
- lint: `make lint` exit 0 (ruff check, ruff format, ESLint with `--max-warnings 0`; also clean on the new tester spec)
- test: `make test` exit 0. pytest 578/578, gjs 1/1, Playwright 14/14 (Chromium fallback: WebKit MiniBrowser is missing `libevent-2.1.so.7` on this host, as documented)
- With the tester spec: `PW_BROWSER=chromium npx playwright test tests/ui/render.spec.mjs tests/ui/render-edge.spec.mjs` gives 20/20 passed

## Done-when criteria
- [x] `make vendor && git status --porcelain app/ui/vendor` reports no changes. The files are untracked, so I checked reproducibility by hash. I ran `sha256sum app/ui/vendor/*` before `make vendor` and again after it, and `diff` showed the two lists are identical (10 files). Each vendored JS/CSS file has the same SHA-256 as its source in `node_modules` (marked.umd.js `392f4d…`, purify.min.js `cd3789…`, highlight.min.js `8ab71e…`, github.min.css `3a9a5d…`, github-dark.min.css `9f208d…`). Installed versions match `package-lock.json` (marked 18.2.0, dompurify 3.4.17, @highlightjs/cdn-assets 11.12.0). The git-status form of this check can only pass once `app/ui/vendor/` is committed.
- [x] `npx playwright test tests/ui/render.spec.mjs`: all 11 passed with `PW_BROWSER=chromium`. Without `PW_BROWSER` the command defaults to WebKit, which cannot launch on this host. That is an environment limit and is documented.
- [x] `grep -rE "https?://" app/ui/index.html app/ui/*.js` gives no output, exit code 1.

## Additional verification
- Error paths of `scripts/vendor.mjs`:
  - A stale file (`stale.js`) in `app/ui/vendor/` is removed and the remaining hashes do not change.
  - A lock file pinning marked 18.1.0, tested in a temporary root, makes the script exit 1 with `vendor: marked 18.2.0 is installed but package-lock.json pins 18.1.0; run npm ci` and write no files.
- Real WebKitGTK 6.0: I loaded `app/ui/index.html` in a `WebKit.WebView` under Xvfb with the CSP in place and called `renderMarkdown` and `enhanceCodeBlocks`. The result had a table with 2 rows, highlighted python keywords, one "Kopiuj kod" button, no `on*` attributes, no `javascript:`, and an external link with `rel`/`data-external`. This covers the WebKit engine that Playwright cannot run here.
- `make run-headless` reached `ui ready`, and `make stop` cleaned up.
- Licenses are vendored for all three packages (MIT; MPL-2.0 OR Apache-2.0; BSD-3-Clause).

## Tests added
- `tests/ui/render-edge.spec.mjs` (9 cases, all pass):
  - Obfuscated and non-web schemes lose their href: `jav&#x09;ascript:`, leading space, `&#106;avascript:`, `vbscript:`, `file:`, `data:` base64, markdown `[ ](  javascript:)` and `<javascript:…>`.
  - Relative, `#fragment`, `mailto:` and `http:` links are kept and get `rel` and `data-external`.
  - Author-supplied `rel="opener"` and `target` are overridden or removed. `data-external` cannot be spoofed on `<a>` without href or on `<span>`.
  - mXSS and dangerous elements are neutralised: math/mglyph/style, noscript title, svg style, object, embed, base, meta refresh, link, button formaction, textarea, select, uppercase `ONERROR`/`ONMOUSEOVER`.
  - HTML inside ```python and ```html blocks stays text after highlighting. An upper-case `PYTHON` language name still highlights.
  - A hostile code-fence info string (`"><img onerror>`) injects no markup.
  - `enhanceCodeBlocks` with `null`, `undefined`, a number, a string or `{}` does not throw.
  - A second click restarts the 1.5 s feedback timer, and the label and aria-label are restored.
  - A copy without clipboard permission shows "Skopiowano" or "Nie skopiowano", restores "Kopiuj", and leaves no `.clipboard-buffer` behind.

## Problems (for the implementer; each actionable)
None.

## Suggestions (non-blocking)
1. `marked.umd.js` and `purify.min.js` end with `sourceMappingURL` comments for `.map` files that are not vendored. WebKit devtools (debug mode) will log a 404 for them. This is harmless, and keeping the files byte-identical is the right trade-off.
2. In `scripts/vendor.mjs`, a source file missing inside a package (for example after an upstream layout change) throws an uncaught ENOENT stack trace instead of the friendly `vendor:` message. The exit code is still non-zero.
3. Relative and `#fragment` links also get `data-external`. That matches the task text, but S3-T4 should decide how `decide-policy` treats non-http(s) targets marked this way.
