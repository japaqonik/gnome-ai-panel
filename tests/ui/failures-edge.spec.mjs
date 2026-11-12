// Edge cases of the S4-T3 error cards and notices (tester): markup from Python is text only.
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');
const AGENTS = [{id: 'fake', name: 'Fake', type: 'acp'}];

let pageErrors;

function dispatch(page, event) {
    return page.evaluate(obj => window.__bridge.dispatch(obj), event);
}

async function startTurn(page, text = 'x') {
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'fake', config_errors: []});
    await expect(page.locator('#chat')).toBeVisible();
    await page.locator('#prompt').fill(text);
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
}

test.beforeEach(async ({page}) => {
    pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.addInitScript({path: mockBridge});
    await page.goto(indexUrl);
    await page.waitForFunction(() => window.aiPanel !== undefined);
});

test.afterEach(() => {
    expect(pageErrors).toEqual([]);
});

test('title, message, hint and labels with markup are shown as text', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {
        type: 'error', kind: 'auth', title: '<i>T</i>', message: '<img src=x onerror=1>',
        hint: '<a href="https://e.com">h</a>', stderr: null, stderr_label: null,
        auth_methods: ['<b>m</b>'], methods_label: '<u>L</u>', blocked: false,
    });
    const card = page.locator('.message--error');
    await expect(card).toHaveCount(1);
    await expect(card.locator('i, img, a, b, u')).toHaveCount(0);
    await expect(card).toContainText('<img src=x onerror=1>');
    await expect(card).toContainText('<b>m</b>');
});

test('notice with markup is text and the reply follows it', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'notice', kind: 'context_lost', text: '<b>utracony</b>'});
    await dispatch(page, {type: 'text_delta', text: 'Echo: b'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    const notice = page.locator('[role="status"]', {hasText: 'utracony'});
    await expect(notice).toHaveText('<b>utracony</b>');
    await expect(notice.locator('b')).toHaveCount(0);
    await expect(page.locator('.message--assistant')).toContainText('Echo: b');
});

test('error without a running turn does not break the page', async ({page}) => {
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'fake', config_errors: []});
    await dispatch(page, {type: 'error', kind: 'crashed', message: 'm', blocked: true});
    await dispatch(page, {type: 'conversation', id: null, messages: []});
    await expect(page.locator('#prompt')).toBeEnabled();
});
