// Theme, font size and the debug state dump of app/ui/chat.js (S3-T4, FR-14, PLAN §12.1).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

const AGENTS = [
    {id: 'fake-echo', name: 'Fake Echo', type: 'acp'},
    {id: 'claude', name: 'Claude', type: 'api'},
];

let pageErrors;

function dispatch(page, event) {
    return page.evaluate(obj => window.__bridge.dispatch(obj), event);
}

function init(page, extra = {}) {
    return dispatch(page, {
        type: 'init', agents: AGENTS, current: 'fake-echo', config_errors: [],
        theme: 'light', font_size: 14, ...extra,
    });
}

async function requestDump(page) {
    await dispatch(page, {type: 'request_dump'});
    const dumps = await page.evaluate(
        () => window.__bridge.messages.filter(m => m.type === 'dump'));
    return dumps.at(-1).state;
}

function background(page) {
    return page.evaluate(() => getComputedStyle(document.body).backgroundColor);
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

test('init.theme forces dark or light whatever the browser prefers', async ({page}) => {
    await page.emulateMedia({colorScheme: 'light'});
    await init(page, {theme: 'dark'});
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    const dark = await background(page);
    expect(await page.evaluate(() => document.getElementById('hljs-theme-light').disabled))
        .toBe(true);
    expect(await page.evaluate(() => document.getElementById('hljs-theme-dark').disabled))
        .toBe(false);

    await page.emulateMedia({colorScheme: 'dark'});
    await init(page, {theme: 'light'});
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    expect(await background(page)).not.toBe(dark);
    expect(await page.evaluate(() => document.getElementById('hljs-theme-dark').disabled))
        .toBe(true);
    expect((await requestDump(page)).theme).toBe('light');
});

test('a second init (desktop theme changed) switches the theme', async ({page}) => {
    await init(page, {theme: 'light'});
    expect((await requestDump(page)).theme).toBe('light');
    await init(page, {theme: 'dark'});
    expect((await requestDump(page)).theme).toBe('dark');
});

test('an invalid theme falls back to the browser preference', async ({page}) => {
    await page.emulateMedia({colorScheme: 'dark'});
    await init(page, {theme: '<b>x</b>'});
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBeUndefined();
    expect((await requestDump(page)).theme).toBe('dark');
});

test('chat.font_size sets the --font-size variable, clamped', async ({page}) => {
    const fontSize = () => page.evaluate(() => getComputedStyle(document.documentElement).fontSize);
    await init(page, {font_size: 18});
    expect(await fontSize()).toBe('18px');
    await init(page, {font_size: 1000});
    expect(await fontSize()).toBe('72px');
    await init(page, {font_size: 'big'}); // ignored: keeps the last valid size
    expect(await fontSize()).toBe('72px');
});

test('request_dump answers with the state of the page', async ({page}) => {
    await init(page);
    await page.locator('#prompt').fill('hej');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, {type: 'text_delta', text: '| a |\n|---|\n| 1 |\n\n```js\nx()\n```\n'});
    let state = await requestDump(page);
    expect(state.busy).toBe(true);
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    state = await requestDump(page);

    expect(state).toMatchObject({
        screen: 'chat', agent: 'fake-echo', badge: 'tools', theme: 'light', busy: false,
        permission_dialog: {open: false, title: ''}, banner: null,
    });
    expect(state.messages.map(m => m.role)).toEqual(['user', 'assistant']);
    expect(state.messages[0].text).toBe('hej');
    const reply = state.messages[1];
    expect(reply.html).toContain('<table');
    expect(reply.html).toContain('class="hljs');
    expect(reply.text).not.toContain('Kopiuj');
    expect(reply.thinking).toBe('');
    expect(reply.tools).toEqual([]);
});

test('dump: error messages, api badge and the empty screen', async ({page}) => {
    await init(page, {current: 'claude'});
    await page.locator('#prompt').fill('x');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'error', message: 'boom', kind: 'crashed'});
    let state = await requestDump(page);
    expect(state.badge).toBe('chat');
    expect(state.messages.at(-1)).toMatchObject({role: 'error', kind: 'crashed'});
    expect(state.messages.at(-1).text).toContain('boom');

    await dispatch(page, {type: 'init', agents: [], current: null, config_errors: []});
    state = await requestDump(page);
    expect(state).toMatchObject({screen: 'empty', agent: null, badge: null});
});

test('links in a reply keep the page where it is when clicked', async ({page}) => {
    // In the app the click goes to decide-policy (app/links.py); here only the markup
    // is checked: every rendered link carries data-external and no target.
    await init(page);
    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, {type: 'text_delta', text: '[a](https://example.com/) [b](rel.html)'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    const anchors = page.locator('.message--assistant a');
    await expect(anchors).toHaveCount(2);
    for (const anchor of await anchors.all()) {
        await expect(anchor).toHaveAttribute('data-external', '');
        expect(await anchor.getAttribute('target')).toBeNull();
    }
});
