// Cancel, error cards, restart notice and the restart-limit block of app/ui/chat.js (S4-T3).
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

function posted(page, type) {
    return page.evaluate(t => window.__bridge.messages.filter(m => m.type === t), type);
}

async function requestDump(page) {
    await dispatch(page, {type: 'request_dump'});
    return (await posted(page, 'dump')).at(-1).state;
}

async function startTurn(page, text = 'x') {
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'fake', config_errors: []});
    await expect(page.locator('#chat')).toBeVisible();
    await page.locator('#prompt').fill(text);
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
}

function crashedError(extra = {}) {
    return {
        type: 'error', kind: 'crashed', title: 'Agent przestał działać',
        message: 'Proces agenta zakończył działanie (kod 3).',
        hint: 'Następna wiadomość uruchomi agenta ponownie.',
        stderr: 'line 1\n<b>boom</b>', stderr_label: 'Ostatnie linie stderr agenta',
        auth_methods: null, methods_label: null, blocked: false, ...extra,
    };
}

const tool = (page, id) => page.locator(`.tool[data-tool-id="${id}"]`);

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

test('stop marks unfinished tool cards cancelled at once', async ({page}) => {
    await startTurn(page);
    for (const [id, status] of [['a', 'in_progress'], ['b', 'pending'], ['c', 'completed'],
        ['d', 'failed']])
        await dispatch(page, {type: 'tool_call', id, title: id, status});
    await page.locator('#stop').click();
    expect((await posted(page, 'cancel')).length).toBe(1);
    await expect(tool(page, 'a')).toHaveAttribute('data-status', 'cancelled');
    await expect(tool(page, 'b')).toHaveAttribute('data-status', 'cancelled');
    await expect(tool(page, 'c')).toHaveAttribute('data-status', 'completed');
    await expect(tool(page, 'd')).toHaveAttribute('data-status', 'failed');
    await expect(tool(page, 'a').locator('.tool__status')).toHaveText('Anulowane');
    // One cancel per turn: the button is disabled until the turn ends.
    await expect(page.locator('#stop')).toBeDisabled();

    await dispatch(page, {type: 'done', stop_reason: 'cancelled'});
    await expect(page.locator('.message__status[data-status="cancelled"]')).toHaveText('Przerwano');
    await expect(page.locator('#send')).toBeVisible();

    // The next turn gets an enabled stop button again.
    await page.locator('#prompt').fill('y');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
    await expect(page.locator('#stop')).toBeEnabled();
});

test('done cancelled without stop also marks unfinished cards', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'tool_call', id: 'a', title: 'a', status: 'in_progress'});
    await dispatch(page, {type: 'done', stop_reason: 'cancelled'});
    await expect(tool(page, 'a')).toHaveAttribute('data-status', 'cancelled');
});

test('done end_turn keeps the tool statuses', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'tool_call', id: 'a', title: 'a', status: 'in_progress'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await expect(tool(page, 'a')).toHaveAttribute('data-status', 'in_progress');
});

test('crashed error shows title, message, hint and collapsed stderr', async ({page}) => {
    await startTurn(page);
    await dispatch(page, crashedError());
    const card = page.locator('.message--error');
    await expect(card).toHaveAttribute('data-kind', 'crashed');
    await expect(card).toHaveAttribute('role', 'alert');
    await expect(card.locator('.message__title')).toHaveText('Agent przestał działać');
    await expect(card.locator('.message__text')).toHaveText(
        'Proces agenta zakończył działanie (kod 3).');
    await expect(card.locator('.message__hint')).toHaveText(
        'Następna wiadomość uruchomi agenta ponownie.');
    const details = card.locator('details.message__stderr');
    await expect(details).not.toHaveAttribute('open', /.*/);
    await expect(details.locator('summary')).toHaveText('Ostatnie linie stderr agenta');
    // stderr is text, never markup.
    await expect(details.locator('pre')).toHaveText('line 1\n<b>boom</b>');
    await expect(details.locator('b')).toHaveCount(0);
    await expect(details.locator('pre')).toBeHidden();
    await details.locator('summary').click();
    await expect(details.locator('pre')).toBeVisible();

    // The empty reply of the failed turn is removed; the dump text holds the stderr.
    await expect(page.locator('.message--assistant')).toHaveCount(0);
    const state = await requestDump(page);
    expect(state.messages.map(m => m.role)).toEqual(['user', 'error']);
    expect(state.messages[1].text).toContain('boom');
    expect(state.messages[1].kind).toBe('crashed');
    await expect(page.locator('#send')).toBeVisible();
    await expect(page.locator('#prompt')).toBeEnabled();
});

test('error after streamed text keeps the partial reply', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'text_delta', text: 'Częściowa odpowiedź'});
    await dispatch(page, crashedError());
    await expect(page.locator('.message--assistant')).toHaveText('Częściowa odpowiedź');
    await expect(page.locator('.message--error')).toHaveCount(1);
});

test('auth error lists the login methods as text', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {
        type: 'error', kind: 'auth', title: 'Agent wymaga zalogowania',
        message: 'Agent nie utworzy sesji, dopóki się nie zalogujesz.',
        hint: 'Zaloguj się w terminalu, np. poleceniem logowania swojego agenta.',
        stderr: null, stderr_label: null,
        auth_methods: ['Fake login: Run `fake-agent login`', '<img src=x>', 7, ''],
        methods_label: 'Dostępne metody logowania:', blocked: false,
    });
    const card = page.locator('.message--error[data-kind="auth"]');
    await expect(card.locator('.message__label')).toHaveText('Dostępne metody logowania:');
    await expect(card.locator('.message__method')).toHaveText([
        'Fake login: Run `fake-agent login`', '<img src=x>']);
    await expect(card.locator('img')).toHaveCount(0);
    await expect(card.locator('.message__hint')).toContainText('Zaloguj się w terminalu');
    await expect(card.locator('details')).toHaveCount(0);
});

test('error without the new fields falls back to the generic title', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'error', message: 'Coś', kind: 'other'});
    const card = page.locator('.message--error');
    await expect(card.locator('.message__title')).toHaveText('Błąd');
    await expect(card.locator('.message__text')).toHaveText('Coś');
    await expect(card.locator('.message__hint')).toHaveCount(0);
});

test('notice goes before the running reply', async ({page}) => {
    await startTurn(page, 'b');
    await dispatch(page, {type: 'notice', kind: 'context_lost',
        text: 'Agent został uruchomiony ponownie, poprzedni kontekst utracony'});
    await dispatch(page, {type: 'text_delta', text: 'Echo: b'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    const state = await requestDump(page);
    expect(state.messages.map(m => m.role)).toEqual(['user', 'notice', 'assistant']);
    expect(state.messages[1].text).toBe(
        'Agent został uruchomiony ponownie, poprzedni kontekst utracony');
    await expect(page.locator('.message--notice')).toHaveAttribute('role', 'status');
    await dispatch(page, {type: 'notice', kind: 'x', text: '<b>t</b>'});
    await expect(page.locator('.message--notice').last()).toHaveText('<b>t</b>');
    expect(await dispatch(page, {type: 'notice', text: 5})).toBe(true);
    await expect(page.locator('.message--notice')).toHaveCount(2);
});

test('blocked error disables sending until a new conversation', async ({page}) => {
    await startTurn(page);
    await dispatch(page, crashedError({blocked: true, hint: 'Rozpocznij nową rozmowę.'}));
    await expect(page.locator('#prompt')).toBeDisabled();
    await expect(page.locator('#send')).toBeDisabled();
    const before = (await posted(page, 'send')).length;
    // Neither Enter nor a scripted submit (debug-send) sends anything.
    await page.evaluate(() => {
        document.getElementById('prompt').value = 'z';
        document.getElementById('composer').requestSubmit();
    });
    expect((await posted(page, 'send')).length).toBe(before);

    const button = page.locator('.message--error [data-action="new-chat"]');
    await expect(button).toHaveText('Nowa rozmowa');
    await button.click();
    expect(await posted(page, 'new_chat')).toEqual([{type: 'new_chat'}]);
    await expect(page.locator('#prompt')).toBeDisabled(); // until Python confirms
    await dispatch(page, {type: 'conversation', id: null, messages: []});
    await expect(page.locator('#prompt')).toBeEnabled();
    await expect(page.locator('#send')).toBeEnabled();
    await page.locator('#prompt').fill('nowa');
    await page.locator('#prompt').press('Enter');
    expect((await posted(page, 'send')).at(-1)).toEqual({type: 'send', text: 'nowa'});
});
