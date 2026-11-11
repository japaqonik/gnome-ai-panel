// Edge cases of app/ui/render.js added by the tester (S3-T1): obfuscated URI schemes,
// attribute spoofing, mXSS payloads, hostile code blocks, copy feedback timing.
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

function hrefs(page) {
    return page.evaluate(() =>
        [...document.querySelectorAll('#out [href]')].map(el => el.getAttribute('href')));
}

test('obfuscated and non-web URI schemes lose their href', async ({page}) => {
    await render(page, [
        '<a href="jav&#x09;ascript:alert(1)">a</a>',
        '<a href=" javascript:alert(2)">b</a>',
        '<a href="&#106;avascript:alert(3)">c</a>',
        '<a href="vbscript:msgbox(4)">d</a>',
        '<a href="file:///etc/passwd">e</a>',
        '[f](  javascript:alert(6))',
        '[g](<javascript:alert(7)>)',
        '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCg4KTwvc2NyaXB0Pg==">h</a>',
    ].join('\n\n'));
    const found = await hrefs(page);
    for (const href of found)
        expect(href).toMatch(/^(https?:|mailto:|#|\/|\.)/i);
    await expect(page.locator('#out [data-external]:not(a[href])')).toHaveCount(0);
});

test('relative, fragment and mailto links are kept and marked external', async ({page}) => {
    await render(page, '[r](./doc.md) [f](#sec) [m](mailto:x@example.com) [h](http://example.com/)\n');
    expect(await hrefs(page)).toEqual(['./doc.md', '#sec', 'mailto:x@example.com', 'http://example.com/']);
    await expect(page.locator('#out a[data-external][rel="noopener noreferrer"]')).toHaveCount(4);
});

test('author-supplied rel, target and data-external cannot be spoofed', async ({page}) => {
    await render(page, [
        '<a href="https://example.com/" rel="opener" target="_blank">x</a>',
        '<a name="n" data-external="1">no href</a>',
        '<span data-external>s</span>',
    ].join('\n\n'));
    const link = page.locator('#out a[href]');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(await link.getAttribute('target')).toBeNull();
    await expect(page.locator('#out [data-external]')).toHaveCount(1);
});

test('mXSS and dangerous elements are neutralised', async ({page}) => {
    const html = await render(page, [
        '<math><mtext><table><mglyph><style><img src=x onerror=alert(1)></style></mglyph></table></mtext></math>',
        '<noscript><p title="</noscript><img src=x onerror=alert(2)>"></noscript>',
        '<svg><style><img src=x onerror=alert(3)></style></svg>',
        '<object data="javascript:alert(4)"></object><embed src="javascript:alert(5)">',
        '<base href="https://evil.example/"><meta http-equiv="refresh" content="0;url=https://evil.example/">',
        '<link rel="stylesheet" href="https://evil.example/x.css">',
        '<button formaction="javascript:alert(6)">b</button><textarea>t</textarea><select></select>',
        '<IMG SRC=x ONERROR=alert(7)>',
        '<a href="https://example.com/" ONMOUSEOVER="alert(8)">m</a>',
    ].join('\n\n'));
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
    const report = await page.evaluate(() => {
        const out = document.getElementById('out');
        const all = [...out.querySelectorAll('*')];
        return {
            bad: out.querySelectorAll('script, style, math, svg, object, embed, base, meta, link, '
                + 'button:not(.code-block__copy), textarea, select, iframe, form').length,
            on: all.flatMap(el => el.getAttributeNames().filter(n => n.toLowerCase().startsWith('on'))),
        };
    });
    expect(report).toEqual({bad: 0, on: []});
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => window.__alerts)).toEqual([]);
});

test('HTML inside code blocks stays text, also when highlighted', async ({page}) => {
    await render(page, [
        '```python\nprint("<script>alert(1)</script>")\n```',
        '```html\n<img src=x onerror=alert(2)>\n```',
        '```PYTHON\nimport os\n```',
    ].join('\n\n'));
    await expect(page.locator('#out script, #out img')).toHaveCount(0);
    await expect(page.locator('#out pre > code').nth(0)).toContainText('<script>alert(1)</script>');
    await expect(page.locator('#out pre > code').nth(1)).toContainText('<img src=x onerror=alert(2)>');
    await expect(page.locator('#out pre > code').nth(2).locator('span.hljs-keyword')).toHaveText('import');
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => window.__alerts)).toEqual([]);
});

test('hostile info string of a code block does not inject markup', async ({page}) => {
    await render(page, '```"><img src=x onerror=alert(1)>\ncode\n```\n');
    await expect(page.locator('#out img')).toHaveCount(0);
    await expect(page.locator('#out .code-block__copy')).toHaveCount(1);
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => window.__alerts)).toEqual([]);
});

test('enhanceCodeBlocks ignores invalid containers', async ({page}) => {
    const ok = await page.evaluate(() => {
        for (const value of [null, undefined, 42, 'pre', {}])
            window.aiPanelRender.enhanceCodeBlocks(value);
        return true;
    });
    expect(ok).toBe(true);
});

test('second click restarts the 1.5 s feedback timer', async ({page, context}) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await render(page, '```js\nlet a = 1;\n```\n');
    const button = page.locator('#out .code-block__copy');
    await button.click();
    await expect(button).toHaveText('Skopiowano');
    await page.waitForTimeout(1000);
    await button.click();
    await page.waitForTimeout(800); // 1.8 s after the first click, 0.8 s after the second
    await expect(button).toHaveText('Skopiowano');
    await expect(button).toHaveAttribute('aria-label', 'Skopiowano');
    await expect(button).toHaveText('Kopiuj', {timeout: 2000});
    await expect(button).toHaveAttribute('aria-label', 'Kopiuj kod');
});

test('copy without clipboard permission still gives feedback and restores the label', async ({page}) => {
    await render(page, '```js\nlet b = 2;\n```\n');
    const button = page.locator('#out .code-block__copy');
    await button.click();
    await expect(button).toHaveText(/^(Skopiowano|Nie skopiowano)$/);
    await expect(button).toHaveText('Kopiuj', {timeout: 2500});
    await expect(page.locator('.clipboard-buffer')).toHaveCount(0);
});
