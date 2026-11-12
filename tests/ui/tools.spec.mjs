// Thinking blocks and tool cards of app/ui/chat.js (S4-T1, FR-9, FR-10).
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

function toolCall(extra = {}) {
    return {
        type: 'tool_call', id: 'call_1', title: 'Odczyt pliku notes.txt', kind: 'read',
        status: 'pending', raw_input: {path: 'notes.txt'}, content: null, ...extra,
    };
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

test('thinking goes into a collapsed <details> with a live header', async ({page}) => {
    await startTurn(page);
    expect(await dispatch(page, {type: 'thinking_delta', text: 'Sprawdzę '})).toBe(true);
    await dispatch(page, {type: 'thinking_delta', text: '<b>plik</b>.'});
    const thinking = assistant(page).locator('details.thinking');
    await expect(thinking).toHaveCount(1);
    await expect(thinking).not.toHaveAttribute('open', /.*/);
    await expect(thinking.locator('summary')).toHaveText('Myśli…');
    await expect(thinking).toHaveAttribute('data-state', 'active');
    // Thinking text is shown as text, never as markup.
    await expect(thinking.locator('b')).toHaveCount(0);
    await expect(thinking.locator('.thinking__body')).not.toBeVisible();

    await dispatch(page, {type: 'text_delta', text: 'Gotowe.'});
    await expect(thinking.locator('summary')).toHaveText('Myślenie');
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await expect(thinking).not.toHaveAttribute('open', /.*/);

    await thinking.locator('summary').click();
    await expect(thinking.locator('.thinking__body')).toHaveText('Sprawdzę <b>plik</b>.');

    const state = await requestDump(page);
    const last = state.messages.at(-1);
    expect(last.thinking).toBe('Sprawdzę <b>plik</b>.');
    expect(last.text.trim()).toBe('Gotowe.');
    expect(last.html).toContain('Gotowe.');
    expect(last.html).not.toContain('Sprawdzę');
});

test('thinking header ends with done even without text', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'thinking_delta', text: 'hmm'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await expect(assistant(page).locator('.thinking summary')).toHaveText('Myślenie');
});

test('tool_call + 2× tool_update → one card that ends completed', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'thinking_delta', text: 'Sprawdzę plik.'});
    expect(await dispatch(page, toolCall())).toBe(true);
    const cards = assistant(page).locator('.tool');
    await expect(cards).toHaveCount(1);
    const card = cards.first();
    await expect(card).toHaveAttribute('data-tool-id', 'call_1');
    await expect(card).toHaveAttribute('data-status', 'pending');
    await expect(card).toHaveAttribute('data-kind', 'read');
    await expect(card.locator('.tool__title')).toHaveText('Odczyt pliku notes.txt');
    await expect(card.locator('.tool__status')).toHaveText('Oczekuje');
    await expect(card.locator('.tool__output')).toBeHidden();
    // The tool call ends the thinking phase.
    await expect(assistant(page).locator('.thinking summary')).toHaveText('Myślenie');

    expect(await dispatch(page, {type: 'tool_update', id: 'call_1', status: 'in_progress'}))
        .toBe(true);
    await expect(card).toHaveAttribute('data-status', 'in_progress');
    await expect(card.locator('.tool__status')).toHaveText('W toku');
    await expect(card.locator('.tool__title')).toHaveText('Odczyt pliku notes.txt');

    await dispatch(page, {
        type: 'tool_update', id: 'call_1', status: 'completed',
        content: [{type: 'content', content: {type: 'text', text: '**zawartość**'}}],
    });
    await dispatch(page, {type: 'text_delta', text: 'Plik zawiera: zawartość.'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});

    await expect(cards).toHaveCount(1);
    await expect(card).toHaveAttribute('data-status', 'completed');
    await expect(card.locator('.tool__status')).toHaveText('Zakończone');
    const output = card.locator('.tool__output');
    await expect(output).toBeVisible();
    await expect(output).not.toHaveAttribute('open', /.*/);
    await output.locator('summary').click();
    await expect(output.locator('strong')).toHaveText('zawartość');

    const input = card.locator('.tool__input');
    await input.locator('summary').click();
    await expect(input.locator('pre')).toHaveText(JSON.stringify({path: 'notes.txt'}, null, 2));

    const state = await requestDump(page);
    const last = state.messages.at(-1);
    expect(last.tools).toEqual([
        {id: 'call_1', title: 'Odczyt pliku notes.txt', status: 'completed'},
    ]);
    expect(last.thinking).toBe('Sprawdzę plik.');
    expect(last.text.trim()).toBe('Plik zawiera: zawartość.');
});

test('raw_input with <script> is shown as text', async ({page}) => {
    await startTurn(page);
    const payload = '<script>window.__pwned = 1</script><img src=x onerror="window.__pwned=2">';
    await dispatch(page, toolCall({title: '<b>tytuł</b>', raw_input: {command: payload}}));
    const card = assistant(page).locator('.tool').first();
    await card.locator('.tool__input summary').click();
    const pre = card.locator('.tool__input pre');
    await expect(pre).toContainText('<script>window.__pwned = 1</script>');
    await expect(card.locator('script, img, b')).toHaveCount(0);
    await expect(card.locator('.tool__title')).toHaveText('<b>tytuł</b>');
    expect(await page.evaluate(() => window.__pwned)).toBeUndefined();

    // A string raw_input is shown as it is.
    await dispatch(page, {type: 'tool_update', id: 'call_1', raw_input: 'ls -la <dir>'});
    await expect(pre).toHaveText('ls -la <dir>');
});

test('tool output: markdown is sanitised, diff is a <pre>', async ({page}) => {
    await startTurn(page);
    await dispatch(page, toolCall({
        status: 'completed',
        content: [
            {type: 'content', content: {type: 'text', text: '<img src=x onerror="window.__pwned=1">ok'}},
            {type: 'diff', path: '/tmp/a.txt', oldText: 'stary', newText: 'nowy\n<script>'},
            {type: 'terminal', terminalId: 'term_1'},
        ],
    }));
    const output = assistant(page).locator('.tool .tool__output');
    await output.locator('summary').click();
    await expect(output.locator('.tool__text')).toContainText('ok');
    await expect(output.locator('[onerror]')).toHaveCount(0);
    await expect(output.locator('pre.tool__diff')).toHaveText(
        '--- /tmp/a.txt\n+++ /tmp/a.txt\n-stary\n+nowy\n+<script>');
    await expect(output.locator('pre.tool__terminal')).toHaveText('Terminal term_1');
    await expect(output.locator('script')).toHaveCount(0);
    expect(await page.evaluate(() => window.__pwned)).toBeUndefined();
});

test('updates of an unknown id are ignored', async ({page}) => {
    await startTurn(page);
    await dispatch(page, toolCall());
    await dispatch(page, {type: 'tool_update', id: 'call_2', status: 'failed', title: 'Obcy'});
    await dispatch(page, {type: 'tool_update', id: 42, status: 'failed'});
    const cards = assistant(page).locator('.tool');
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toHaveAttribute('data-status', 'pending');
    await expect(page.getByText('Obcy')).toHaveCount(0);
    // An update with an unknown status changes nothing either.
    await dispatch(page, {type: 'tool_update', id: 'call_1', status: 'exploded'});
    await expect(cards.first()).toHaveAttribute('data-status', 'pending');
});

test('several tools keep their order; repeated tool_call updates its card', async ({page}) => {
    await startTurn(page);
    await dispatch(page, toolCall({id: 'a', title: 'Pierwsze'}));
    await dispatch(page, toolCall({id: 'b', title: 'Drugie'}));
    await dispatch(page, toolCall({id: 'a', title: 'Pierwsze (ponownie)', status: 'failed'}));
    await dispatch(page, {type: 'tool_update', id: 'b', status: 'completed'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    const state = await requestDump(page);
    expect(state.messages.at(-1).tools).toEqual([
        {id: 'a', title: 'Pierwsze (ponownie)', status: 'failed'},
        {id: 'b', title: 'Drugie', status: 'completed'},
    ]);
});

test('tool card without title or status falls back to defaults', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'tool_call', id: 'c'});
    const card = assistant(page).locator('.tool').first();
    await expect(card.locator('.tool__title')).toHaveText('Narzędzie');
    await expect(card).toHaveAttribute('data-status', 'pending');
    await expect(card.locator('.tool__input')).toBeHidden();
});

test('tool_update after the turn ended does not touch the old card', async ({page}) => {
    await startTurn(page);
    await dispatch(page, toolCall());
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await dispatch(page, {type: 'tool_update', id: 'call_1', status: 'completed'});
    await expect(assistant(page).locator('.tool').first())
        .toHaveAttribute('data-status', 'pending');
});
