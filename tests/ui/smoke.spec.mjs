// Smoke test of app/ui/index.html loaded through file:// with the mock bridge (S1-T3).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

test.beforeEach(async ({page}) => {
    await page.addInitScript({path: mockBridge});
});

test('page loads from file:// and shows the empty state', async ({page}) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    const response = await page.goto(indexUrl);
    expect(response === null || response.ok()).toBe(true);

    await expect(page).toHaveTitle('AI Panel');
    await expect(page.locator('#empty-state')).toBeVisible();
    await expect(page.locator('#add-agent')).toHaveText('Dodaj agenta');
    expect(errors).toEqual([]);
});

test('document has a Content-Security-Policy meta tag', async ({page}) => {
    await page.goto(indexUrl);
    const csp = page.locator('meta[http-equiv="Content-Security-Policy"]');
    await expect(csp).toHaveCount(1);
    await expect(csp).toHaveAttribute('content', /default-src 'none'/);
    await expect(csp).toHaveAttribute('content', /script-src 'self'/);
});

test('bridge receives {type: "ready"} exactly once', async ({page}) => {
    await page.goto(indexUrl);
    await expect.poll(() => page.evaluate(() => window.__bridge.messages)).toEqual([{type: 'ready'}]);
});
