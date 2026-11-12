// Extra edge cases of app/ui/chat.js added by the tester (S3-T2).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

const AGENTS = [{id: 'fake-echo', name: 'Fake Echo', type: 'acp'}];

let pageErrors;

function dispatch(page, event) {
    return page.evaluate(obj => window.__bridge.dispatch(obj), event);
}

function sent(page) {
    return page.evaluate(() => window.__bridge.messages.filter(m => m.type !== 'ready'));
}

async function startChat(page, init = {agents: AGENTS, current: 'fake-echo'}) {
    await dispatch(page, {type: 'init', config_errors: [], ...init});
    await expect(page.locator('#chat')).toBeVisible();
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

test('ready is posted exactly once, after window.aiPanel exists', async ({page}) => {
    const msgs = await page.evaluate(() => window.__bridge.messages);
    expect(msgs).toEqual([{type: 'ready'}]);
    expect(await page.evaluate(() => Object.isFrozen(window.aiPanel))).toBe(true);
});

test('before init the empty state is shown and the chat is hidden', async ({page}) => {
    await expect(page.locator('#empty-state')).toBeVisible();
    await expect(page.locator('#chat')).toBeHidden();
});

test('a quick double Enter sends only once', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('raz');
    await page.evaluate(() => {
        const field = document.getElementById('prompt');
        for (let i = 0; i < 2; i++)
            field.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
    });
    expect(await sent(page)).toEqual([{type: 'send', text: 'raz'}]);
});

test('Enter during a turn does not insert a newline into the draft', async ({page}) => {
    await startChat(page);
    const prompt = page.locator('#prompt');
    await prompt.fill('a');
    await prompt.press('Enter');
    await prompt.fill('szkic');
    await prompt.press('Enter');
    await expect(prompt).toHaveValue('szkic');
});

test('stop before turn_start (pending send) posts cancel', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('x');
    await page.locator('#prompt').press('Enter');
    await expect(page.locator('#stop')).toBeVisible();
    await page.locator('#stop').click();
    expect(await sent(page)).toEqual([{type: 'send', text: 'x'}, {type: 'cancel'}]);
});

test('each turn gets its own assistant message', async ({page}) => {
    await startChat(page);
    for (const word of ['pierwsza', 'druga']) {
        await dispatch(page, {type: 'turn_start'});
        await dispatch(page, {type: 'text_delta', text: word});
        await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    }
    const replies = page.locator('.message--assistant');
    await expect(replies).toHaveCount(2);
    await expect(replies.nth(0)).toHaveText('pierwsza');
    await expect(replies.nth(1)).toHaveText('druga');
});

test('error outside a turn shows a bubble and leaves the idle state', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'error', kind: 'not_found', message: 'Brak komendy'});
    await expect(page.locator('.message--error')).toHaveAttribute('data-kind', 'not_found');
    await expect(page.locator('#send')).toBeVisible();
    await expect(page.locator('#stop')).toBeHidden();
});

test('error without message or kind still renders a readable bubble', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'error'});
    const error = page.locator('.message--error');
    await expect(error).toHaveAttribute('data-kind', 'unknown');
    await expect(error.locator('.message__text')).toHaveText('Błąd');
});

test('max_tokens and refusal stop reasons get markers, unknown reasons do not', async ({page}) => {
    await startChat(page);
    for (const reason of ['max_tokens', 'refusal', 'something_new']) {
        await dispatch(page, {type: 'turn_start'});
        await dispatch(page, {type: 'text_delta', text: reason});
        await dispatch(page, {type: 'done', stop_reason: reason});
    }
    await expect(page.locator('[data-status="max_tokens"]')).toHaveCount(1);
    await expect(page.locator('[data-status="refusal"]')).toHaveCount(1);
    await expect(page.locator('.message__status')).toHaveCount(2);
});

test('agent names are shown as text, not HTML', async ({page}) => {
    await startChat(page, {agents: [{id: 'x', name: '<img src=x onerror="window.__xss=1">'}], current: 'x'});
    await expect(page.locator('.chat-header img')).toHaveCount(0);
    await expect(page.locator('#agent option:checked'))
        .toHaveText('<img src=x onerror="window.__xss=1">');
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
});

test('init with malformed agent entries does not throw', async ({page}) => {
    // Entries without a string id are dropped; with none left the empty screen is shown.
    await dispatch(page, {type: 'init', config_errors: [], agents: [null, 'str', {id: 7}],
        current: 'x'});
    await expect(page.locator('#empty-state')).toBeVisible();
    await expect(page.locator('#agent option')).toHaveCount(0);
    await startChat(page, {agents: [null, {id: 7}, {id: 'ok'}], current: 'x'});
    await expect(page.locator('#agent option')).toHaveCount(1);
    await expect(page.locator('#agent option:checked')).toHaveText('ok');
    await dispatch(page, {type: 'init', agents: 'nope'});
    await expect(page.locator('#empty-state')).toBeVisible();
});

test('a new prompt after a cancelled turn can be sent', async ({page}) => {
    await startChat(page);
    const prompt = page.locator('#prompt');
    await prompt.fill('a');
    await prompt.press('Enter');
    await page.locator('#stop').click();
    await dispatch(page, {type: 'done', stop_reason: 'cancelled'});
    await prompt.fill('b');
    await prompt.press('Enter');
    expect(await sent(page)).toEqual([
        {type: 'send', text: 'a'}, {type: 'cancel'}, {type: 'send', text: 'b'},
    ]);
});

test('visible chat texts come from strings.js', async ({page}) => {
    await startChat(page);
    const s = await page.evaluate(() => window.aiPanelStrings);
    await expect(page.locator('#send')).toHaveText(s.send);
    await expect(page.locator('#prompt')).toHaveAttribute('placeholder', s.promptPlaceholder);
    await page.locator('#prompt').fill('x');
    await page.locator('#prompt').press('Enter');
    await expect(page.locator('#stop')).toHaveText(s.stop);
});
