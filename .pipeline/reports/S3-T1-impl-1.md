# Implementation report S3-T1 attempt 1
## Changes
- `package.json`, `package-lock.json`: added devDependency `@highlightjs/cdn-assets` 11.12.0 (exact pin) and removed the unused `highlight.js` package. The `highlight.js` npm package ships only CommonJS/ES sources and has no browser bundle; `@highlightjs/cdn-assets` is the official prebuilt build of the same project and version (`highlight.min.js` with the "common" set of 36 languages, styles, LICENSE). Installed from the npm registry, so it is pinned in the lock file like the other libraries. Nothing is loaded from a CDN at runtime.
- `scripts/vendor.mjs` (new): copies byte-identical files from `node_modules` into `app/ui/vendor/`: `marked.umd.js`, `purify.min.js`, `highlight.min.js`, `github.min.css`, `github-dark.min.css`, and the licenses `LICENSE.marked.txt`, `LICENSE.dompurify.txt`, `LICENSE-MPL.dompurify.txt`, `LICENSE.highlight.js.txt`. It also writes `vendor.json` (package, locked version, license, source path and SHA-256 of each file). It exits 1 when an installed version differs from `package-lock.json`, and it removes stale files from `vendor/`.
- `Makefile`: `make vendor` now runs `node scripts/vendor.mjs` (it was `not_implemented`).
- `app/ui/vendor/` (new, to be committed): the generated files.
- `app/ui/render.js` (new): `window.aiPanelRender.renderMarkdown(text)` uses its own `marked.Marked({gfm:true})` instance and its own `DOMPurify(window)` instance. The sanitiser uses the HTML profile only (no SVG/MathML) and forbids `style`, `script`, `iframe`, `frame(set)`, `object`, `embed`, `form`, form controls, `base`, `link` and `meta`. It also forbids the attributes `style`, `target`, `formaction` and `data-*`. Allowed URIs are limited to `http(s):`, `mailto:` and relative links, and a hook removes any `on*` attribute that gets through. Every `<a href>` gets `rel="noopener noreferrer"` and `data-external`. Non-string or empty input returns `''`. `enhanceCodeBlocks(container)` is idempotent (`data-enhanced`): it highlights blocks with a known language through `hljs.highlight`, which escapes the source, and adds the `hljs` class to every block. It wraps each block in `.code-block` with a language label and a "Kopiuj" button (`aria-label="Kopiuj kod"`). The button uses `navigator.clipboard.writeText` and falls back to `execCommand('copy')` if that fails. It then shows "Skopiowano" (or "Nie skopiowano") for 1.5 s and restores both the text and the aria-label.
- `app/ui/strings.js` (new): the UI texts for the copy button (NFR-8).
- `app/ui/index.html`: loads the vendor CSS (github-dark only under `prefers-color-scheme: dark`) and these scripts as classic `defer` scripts: vendor, `strings.js`, `render.js`, `app.js`. The CSP is unchanged.
- `app/ui/style.css`: styles for the code block, the toolbar, the copy button and the off-screen copy buffer.
- `tests/ui/render.spec.mjs` (new, 11 tests): libraries load; lists; GFM table (1 `table`, 2 `tr`); a ```python block gets `hljs`, `hljs-keyword` spans and a copy button; blocks with no language or an unknown one; idempotence; copy to clipboard with `grantPermissions` and the label restored after about 1.5 s; link attributes; XSS (img onerror, script, `javascript:` links in markdown and HTML with mixed case, iframe, form, style tag and attribute, svg onload, details ontoggle, `data:` link) with no `alert` call; non-string input; 100 KB of markdown rendered, highlighted and laid out in ≤ 2 s.
- `README.md`: added `make vendor` to the table and a paragraph about the vendored files, how to update them, and `render.js`.

## Problems from previous report
- None. No earlier S3-T1 report exists.

## How to verify
- `make vendor && git status --porcelain app/ui/vendor`: after the git agent commits `app/ui/vendor/`, the output is empty. Before the commit the directory shows as `??`. I checked that a second `make vendor` produces identical SHA-256 sums.
- `npx playwright test tests/ui/render.spec.mjs` → 11 passed.
- `grep -rE "https?://" app/ui/index.html app/ui/*.js` → no output, exit code 1.
- Sanity check of the XSS test: with `sanitize` removed from `render.js`, the XSS test fails. I then restored the code.

## Command results
- build: ok, lint: ok, test: pytest 578 passed, gjs 1 passed, Playwright 14/14 passed (on Chromium, because WebKit lacks `libevent-2.1.so.7` on this host and falls back automatically).

## Known limitations / deviations from plan
- The highlight.js browser build comes from `@highlightjs/cdn-assets`, not from `highlight.js` (see above). It is the same upstream release, 11.12.0, under BSD-3-Clause.
- `marked.umd.js` and `purify.min.js` end with a `sourceMappingURL` comment, but the `.map` files are not vendored. That reference is relative and is only read by devtools, so it is not a remote resource.
- The tests ran on Chromium. To run them on WebKit, first run `sudo npx playwright install-deps webkit`.
