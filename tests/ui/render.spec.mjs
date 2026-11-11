// Markdown rendering, sanitisation and code blocks of app/ui/render.js (S3-T1).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

let pageErrors;

test.beforeEach(async ({page}) => {
    pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.addInitScript({path: mockBridge});
    await page.addInitScript(() => {
        window.__alerts = [];
        window.alert = value => window.__alerts.push(String(value));
    });
    await page.goto(indexUrl);
    await page.waitForFunction(() => window.aiPanelRender !== undefined);
});

test.afterEach(() => {
    expect(pageErrors).toEqual([]);
});

// Renders `markdown` into a fresh #out element, enhances its code blocks, returns the HTML
// string produced by renderMarkdown.
function render(page, markdown) {
    return page.evaluate(md => {
        document.getElementById('out')?.remove();
        const out = document.createElement('div');
        out.id = 'out';
        const html = window.aiPanelRender.renderMarkdown(md);
        out.innerHTML = html;
        window.aiPanelRender.enhanceCodeBlocks(out);
        document.body.append(out);
        return html;
    }, markdown);
}

test('vendored libraries load from file:// without errors', async ({page}) => {
    const types = await page.evaluate(() => [typeof window.marked?.Marked, typeof window.DOMPurify,
        typeof window.hljs?.highlight, typeof window.aiPanelRender.renderMarkdown,
        typeof window.aiPanelRender.enhanceCodeBlocks]);
    expect(types).toEqual(['function', 'function', 'function', 'function', 'function']);
    expect(await page.evaluate(() => window.hljs.getLanguage('python') !== undefined)).toBe(true);
});

test('lists', async ({page}) => {
    await render(page, '- one\n- two\n- three\n\n1. first\n2. second\n');
    await expect(page.locator('#out ul > li')).toHaveCount(3);
    await expect(page.locator('#out ol > li')).toHaveCount(2);
    await expect(page.locator('#out ul > li').nth(1)).toHaveText('two');
});

test('GFM table has a header row and a body row', async ({page}) => {
    await render(page, '| Name | Value |\n|:-----|------:|\n| a | 1 |\n');
    const table = page.locator('#out table');
    await expect(table).toHaveCount(1);
    await expect(table.locator('tr')).toHaveCount(2);
    await expect(table.locator('th').first()).toHaveText('Name');
    await expect(table.locator('td').last()).toHaveText('1');
});

test('python code block is highlighted and gets a copy button', async ({page}) => {
    await render(page, '```python\ndef f(x):\n    return x + 1\n```\n');
    const code = page.locator('#out pre > code');
    await expect(code).toHaveClass(/(^|\s)hljs(\s|$)/);
    await expect(code).toHaveClass(/language-python/);
    await expect(code.locator('span.hljs-keyword').first()).toHaveText('def');
    const button = page.locator('#out .code-block button[aria-label="Kopiuj kod"]');
    await expect(button).toHaveCount(1);
    await expect(button).toHaveText('Kopiuj');
    await expect(page.locator('#out .code-block__lang')).toHaveText('python');
});

test('code block without or with an unknown language still gets hljs class and button', async ({page}) => {
    await render(page, '```\nplain <b>text</b>\n```\n\n```nosuchlang\nx\n```\n');
    await expect(page.locator('#out pre > code.hljs')).toHaveCount(2);
    await expect(page.locator('#out pre > code').first()).toHaveText('plain <b>text</b>\n');
    await expect(page.locator('#out pre b')).toHaveCount(0);
    await expect(page.locator('#out .code-block__copy')).toHaveCount(2);
});

test('enhanceCodeBlocks is idempotent', async ({page}) => {
    await render(page, '```js\nlet a = 1;\n```\n');
    await page.evaluate(() => window.aiPanelRender.enhanceCodeBlocks(document.getElementById('out')));
    await expect(page.locator('#out .code-block')).toHaveCount(1);
    await expect(page.locator('#out .code-block__copy')).toHaveCount(1);
});

test('copy button copies the code and shows feedback for 1.5 s', async ({page, context}) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await render(page, '```python\nprint("hi")\nx = 2\n```\n');
    const button = page.locator('#out button[aria-label="Kopiuj kod"]');
    await button.click();
    await expect(page.locator('#out .code-block__copy')).toHaveText('Skopiowano');
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('print("hi")\nx = 2');
    const restoredAfter = await page.evaluate(() => new Promise(resolve => {
        const start = performance.now();
        const button = document.querySelector('#out .code-block__copy');
        const observer = new MutationObserver(() => {
            if (button.textContent === 'Kopiuj') {
                observer.disconnect();
                resolve(performance.now() - start);
            }
        });
        observer.observe(button, {childList: true, characterData: true, subtree: true});
    }));
    expect(restoredAfter).toBeGreaterThan(1000);
    expect(restoredAfter).toBeLessThan(2500);
    await expect(button).toHaveText('Kopiuj');
});

test('links get rel="noopener noreferrer" and data-external', async ({page}) => {
    await render(page, '[site](https://example.com/) and <mailto:a@example.com>\n');
    const links = page.locator('#out a');
    await expect(links).toHaveCount(2);
    for (const link of await links.all()) {
        await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
        await expect(link).toHaveAttribute('data-external', '');
    }
    await expect(links.first()).toHaveAttribute('href', 'https://example.com/');
});

test('XSS: scripts, event handlers and javascript: links are removed', async ({page}) => {
    const payload = [
        '<img src=x onerror=alert(1)>',
        '<script>alert(2)</script>',
        '[a](javascript:alert(3))',
        '<a href="javascript:alert(4)">b</a>',
        '<a href="JaVaScRiPt:alert(5)">c</a>',
        '<iframe src="javascript:alert(6)"></iframe>',
        '<form action="javascript:alert(7)"><input name=q></form>',
        '<div style="background:red" onclick="alert(8)" data-external="1">d</div>',
        '<svg onload=alert(9)><circle r=1></circle></svg>',
        '<style>body{display:none}</style>',
        '<details open ontoggle=alert(10)>e</details>',
        '[f](data:text/html,<script>alert(11)</script>)',
    ].join('\n\n');
    const html = await render(page, payload);
    expect(html).not.toMatch(/<script/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    expect(html).not.toMatch(/javascript:/i);

    const report = await page.evaluate(() => {
        const out = document.getElementById('out');
        const all = [...out.querySelectorAll('*')];
        return {
            scripts: out.querySelectorAll('script').length,
            forbidden: out.querySelectorAll('iframe, form, style, svg, object, embed').length,
            onAttributes: all.flatMap(el => el.getAttributeNames().filter(n => n.startsWith('on'))),
            styleAttributes: all.filter(el => el.hasAttribute('style')).length,
            badHrefs: [...out.querySelectorAll('[href]')].map(el => el.getAttribute('href'))
                .filter(href => !/^(https?:|mailto:|#|\/|\.)/i.test(href)),
            externalWithoutHref: out.querySelectorAll('[data-external]:not(a[href])').length,
        };
    });
    expect(report).toEqual({
        scripts: 0, forbidden: 0, onAttributes: [], styleAttributes: 0, badHrefs: [],
        externalWithoutHref: 0,
    });
    await expect(page.locator('#out a[href^="javascript:" i]')).toHaveCount(0);
    // Give a would-be handler (img onerror) time to fire.
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => window.__alerts)).toEqual([]);
});

test('renderMarkdown returns an empty string for non-text input', async ({page}) => {
    const results = await page.evaluate(() =>
        [undefined, null, 42, {}, ''].map(value => window.aiPanelRender.renderMarkdown(value)));
    expect(results).toEqual(['', '', '', '', '']);
});

test('100 KB of markdown renders in at most 2 s', async ({page}) => {
    const elapsed = await page.evaluate(() => {
        const chunk = [
            '## Sekcja',
            'Akapit z **pogrubieniem**, `kodem` i [linkiem](https://example.com/).',
            '- punkt pierwszy\n- punkt drugi\n  - zagnieżdżony',
            '| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |',
            '```python\nfor i in range(10):\n    print(i * 2)  # komentarz\n```',
            '```js\nconst x = [1, 2, 3].map(v => v + 1);\n```',
        ].join('\n\n') + '\n\n';
        const markdown = chunk.repeat(Math.ceil(100 * 1024 / chunk.length));
        const start = performance.now();
        const out = document.createElement('div');
        out.id = 'out';
        out.innerHTML = window.aiPanelRender.renderMarkdown(markdown);
        window.aiPanelRender.enhanceCodeBlocks(out);
        document.body.append(out);
        void out.offsetHeight; // include layout
        return {ms: performance.now() - start, size: markdown.length,
            tables: out.querySelectorAll('table').length,
            highlighted: out.querySelectorAll('code.hljs').length};
    });
    expect(elapsed.size).toBeGreaterThanOrEqual(100 * 1024);
    expect(elapsed.tables).toBeGreaterThan(100);
    expect(elapsed.highlighted).toBeGreaterThan(200);
    expect(elapsed.ms).toBeLessThanOrEqual(2000);
});
