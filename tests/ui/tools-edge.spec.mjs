// Edge cases of thinking blocks and tool cards in app/ui/chat.js (S4-T1, tester).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

const AGENTS = [{id: 'fake-tool', name: 'Fake Tool', type: 'acp'}];

let pageErrors;

function dispatch(page, event) {
    return page.evaluate(obj => window.__bridge.dispatch(obj), event);
}

async function requestDump(page) {
    await dispatch(page, {type: 'request_dump'});
    const dumps = await page.evaluate(
        () => window.__bridge.messages.filter(m => m.type === 'dump'));
    return dumps.at(-1).state;
}

async function startTurn(page, text = 'x') {
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'fake-tool', config_errors: []});
    await expect(page.locator('#chat')).toBeVisible();
    await page.locator('#prompt').fill(text);
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
}

const assistant = page => page.locator('.message--assistant').last();

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

test('malformed tool events are ignored without page errors', async ({page}) => {
    await startTurn(page);
    for (const event of [
        {type: 'tool_call'},
        {type: 'tool_call', id: ''},
        {type: 'tool_call', id: 7},
        {type: 'tool_call', id: 'x'.repeat(257)},
        {type: 'tool_update'},
        {type: 'tool_update', id: null, status: 'completed'},
        {type: 'thinking_delta'},
        {type: 'thinking_delta', text: 5},
        {type: 'thinking_delta', text: ''},
    ])
        await dispatch(page, event);
    await expect(assistant(page).locator('.tool')).toHaveCount(0);
    await expect(assistant(page).locator('details.thinking')).toHaveCount(0);
});

test('tool_update keeps the fields it does not carry', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {
        type: 'tool_call', id: 'a', title: 'Tytuł', status: 'in_progress',
        raw_input: {cmd: 'ls'},
    });
    await dispatch(page, {type: 'tool_update', id: 'a', title: null, raw_input: null});
    const card = assistant(page).locator('.tool').first();
    await expect(card.locator('.tool__title')).toHaveText('Tytuł');
    await expect(card).toHaveAttribute('data-status', 'in_progress');
    await expect(card.locator('.tool__input .tool__content')).toHaveText(/"cmd": "ls"/);
});

test('every ACP status sets data-status and a label', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'tool_call', id: 'a', title: 'A'});
    const card = assistant(page).locator('.tool').first();
    for (const status of ['in_progress', 'failed', 'cancelled', 'completed', 'pending']) {
        await dispatch(page, {type: 'tool_update', id: 'a', status});
        await expect(card).toHaveAttribute('data-status', status);
        await expect(card.locator('.tool__status')).not.toHaveText('');
    }
});

test('thinking after a tool card still sits above the cards and the body', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'tool_call', id: 'a', title: 'A'});
    await dispatch(page, {type: 'text_delta', text: 'Treść'});
    await dispatch(page, {type: 'thinking_delta', text: 'późna myśl'});
    const order = await assistant(page).evaluate(node =>
        [...node.children].map(child => child.className.split(' ')[0]));
    const thinking = order.indexOf('thinking');
    const tools = order.indexOf('tools');
    expect(thinking).toBeGreaterThanOrEqual(0);
    expect(thinking).toBeLessThan(tools);
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    const message = (await requestDump(page)).messages.at(-1);
    expect(message.thinking).toBe('późna myśl');
    expect(message.text).not.toContain('późna myśl');
    await expect(assistant(page).locator('details.thinking summary')).toHaveText('Myślenie');
});

test('tool output text with an event handler is sanitised', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {
        type: 'tool_call', id: 'a', title: 'A', status: 'completed',
        content: [{type: 'content', content: {type: 'text',
            text: '<img src=x onerror="window.__pwned=1"> **b**'}}],
    });
    const output = assistant(page).locator('.tool__output');
    await expect(output.locator('strong')).toHaveText('b');
    expect(await output.locator('img[onerror]').count()).toBe(0);
    expect(await page.evaluate(() => window.__pwned)).toBeUndefined();
});

test('new conversation drops the cards; an update of an old id is ignored', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'tool_call', id: 'a', title: 'A'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await dispatch(page, {type: 'conversation', messages: []});
    await expect(page.locator('.tool')).toHaveCount(0);
    await startTurn(page, 'y');
    await dispatch(page, {type: 'tool_update', id: 'a', status: 'completed'});
    await expect(page.locator('.tool')).toHaveCount(0);
});
