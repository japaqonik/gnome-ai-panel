// Chat interactions of app/ui/chat.js with the mock bridge (S3-T2, FR-7, FR-8).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

const AGENTS = [
    {id: 'fake-echo', name: 'Fake Echo', type: 'acp'},
    {id: 'other', name: 'Other', type: 'acp'},
];

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

test('init with agents shows the chat with the current agent in the header', async ({page}) => {
    await startChat(page, {agents: AGENTS, current: 'other'});
    await expect(page.locator('#empty-state')).toBeHidden();
    await expect(page.locator('#agent')).toHaveValue('other');
    await expect(page.locator('#agent option:checked')).toHaveText('Other');
    await expect(page.locator('#messages')).toHaveAttribute('aria-live', 'polite');
    await expect(page.locator('#prompt')).toBeFocused();
    await expect(page.locator('#send')).toBeVisible();
    await expect(page.locator('#stop')).toBeHidden();
});

test('init with an unknown current agent falls back to the first one', async ({page}) => {
    await startChat(page, {agents: AGENTS, current: 'missing'});
    await expect(page.locator('#agent')).toHaveValue('fake-echo');
    await expect(page.locator('#agent option:checked')).toHaveText('Fake Echo');
});

test('init with no agents shows #empty-state', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'init', agents: [], current: null, config_errors: []});
    await expect(page.locator('#empty-state')).toBeVisible();
    await expect(page.locator('#chat')).toBeHidden();
});

test('Enter sends the prompt and shows it as a user message', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('Cześć <b>agencie</b>');
    await page.locator('#prompt').press('Enter');
    expect(await sent(page)).toEqual([{type: 'send', text: 'Cześć <b>agencie</b>'}]);
    await expect(page.locator('#prompt')).toHaveValue('');
    const user = page.locator('.message--user');
    await expect(user).toHaveCount(1);
    await expect(user).toHaveText('Cześć <b>agencie</b>');
    await expect(user.locator('b')).toHaveCount(0);
});

test('the send button sends too', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('klik');
    await page.locator('#send').click();
    expect(await sent(page)).toEqual([{type: 'send', text: 'klik'}]);
});

test('Shift+Enter inserts a newline and does not send', async ({page}) => {
    await startChat(page);
    const prompt = page.locator('#prompt');
    await prompt.pressSequentially('a');
    await prompt.press('Shift+Enter');
    await prompt.pressSequentially('b');
    await expect(prompt).toHaveValue('a\nb');
    expect(await sent(page)).toEqual([]);

    await prompt.press('Enter');
    expect(await sent(page)).toEqual([{type: 'send', text: 'a\nb'}]);
});

test('an empty or whitespace-only prompt is not sent', async ({page}) => {
    await startChat(page);
    const prompt = page.locator('#prompt');
    await prompt.press('Enter');
    await prompt.fill('   \n  ');
    await prompt.press('Enter');
    await page.locator('#send').click();
    expect(await sent(page)).toEqual([]);
    await expect(page.locator('.message')).toHaveCount(0);
    await expect(page.locator('#send')).toBeVisible();
});

test('during a turn #stop replaces #send and Enter does not send', async ({page}) => {
    await startChat(page);
    const prompt = page.locator('#prompt');
    await prompt.fill('pierwsze');
    await prompt.press('Enter');
    await dispatch(page, {type: 'turn_start'});

    await expect(page.locator('#stop')).toBeVisible();
    await expect(page.locator('#send')).toBeHidden();
    await expect(page.locator('#messages')).toHaveAttribute('aria-busy', 'true');

    await prompt.fill('drugie');
    await prompt.press('Enter');
    expect(await sent(page)).toEqual([{type: 'send', text: 'pierwsze'}]);
    // The draft stays for the next turn.
    await expect(prompt).toHaveValue('drugie');
});

test('turn_start without a local send also enters the turn state', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'turn_start'});
    await expect(page.locator('#stop')).toBeVisible();
    await expect(page.locator('.message--assistant')).toHaveCount(1);
});

test('clicking stop posts cancel', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('długo');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
    await page.locator('#stop').click();
    expect(await sent(page)).toEqual([{type: 'send', text: 'długo'}, {type: 'cancel'}]);
});

test('50 text_delta events give one assistant message with the full text', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'turn_start'});
    const renders = await page.evaluate(() => {
        // Count frame callbacks requested while the deltas arrive in one task.
        let requested = 0;
        const original = window.requestAnimationFrame;
        window.requestAnimationFrame = callback => {
            requested += 1;
            return original.call(window, callback);
        };
        for (let i = 0; i < 50; i++)
            window.__bridge.dispatch({type: 'text_delta', text: `w${i} `});
        window.requestAnimationFrame = original;
        return requested;
    });
    expect(renders).toBe(1);

    const expected = Array.from({length: 50}, (_, i) => `w${i}`).join(' ');
    const assistant = page.locator('.message--assistant');
    await expect(assistant).toHaveCount(1);
    await expect(assistant).toHaveText(expected);

    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await expect(assistant).toHaveCount(1);
    await expect(assistant).toHaveText(expected);
    await expect(page.locator('.message__status')).toHaveCount(0);
});

test('streamed markdown is rendered, sanitised and code blocks are enhanced', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'turn_start'});
    const chunks = ['| a | b |\n', '|---|---|\n| 1 | 2 |\n\n', '```python\ndef f():\n',
        '    return 1\n```\n', '<img src=x onerror="window.__xss=1">'];
    for (const text of chunks)
        await dispatch(page, {type: 'text_delta', text});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});

    const body = page.locator('.message--assistant .message__body');
    await expect(body.locator('table tr')).toHaveCount(2);
    await expect(body.locator('pre code.hljs .hljs-keyword').first()).toHaveText('def');
    await expect(body.locator('.code-block__copy')).toHaveCount(1);
    await expect(body.locator('[onerror]')).toHaveCount(0);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
});

test('done renders the buffer immediately, without waiting for a frame', async ({page}) => {
    await startChat(page);
    const html = await page.evaluate(() => {
        window.__bridge.dispatch({type: 'turn_start'});
        window.__bridge.dispatch({type: 'text_delta', text: '**gotowe**'});
        window.__bridge.dispatch({type: 'done', stop_reason: 'end_turn'});
        return document.querySelector('.message--assistant .message__body').innerHTML;
    });
    expect(html).toContain('<strong>gotowe</strong>');
});

test('done restores #send and the next prompt can be sent', async ({page}) => {
    await startChat(page);
    const prompt = page.locator('#prompt');
    await prompt.fill('raz');
    await prompt.press('Enter');
    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, {type: 'text_delta', text: 'Echo: raz'});
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});

    await expect(page.locator('#send')).toBeVisible();
    await expect(page.locator('#stop')).toBeHidden();
    await expect(page.locator('#messages')).toHaveAttribute('aria-busy', 'false');

    await prompt.fill('dwa');
    await prompt.press('Enter');
    expect(await sent(page)).toEqual([{type: 'send', text: 'raz'}, {type: 'send', text: 'dwa'}]);
});

test('done with cancelled marks the reply "Przerwano"', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, {type: 'text_delta', text: 'częściowa odpowiedź'});
    await dispatch(page, {type: 'done', stop_reason: 'cancelled'});

    const assistant = page.locator('.message--assistant');
    await expect(assistant).toHaveCount(1);
    await expect(assistant.locator('.message__body')).toHaveText('częściowa odpowiedź');
    await expect(assistant.locator('.message__status[data-status="cancelled"]'))
        .toHaveText('Przerwano');
    await expect(page.locator('#send')).toBeVisible();
});

test('cancel before any reply still shows "Przerwano"', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('x');
    await page.locator('#prompt').press('Enter');
    await page.locator('#stop').click();
    await dispatch(page, {type: 'done', stop_reason: 'cancelled'});
    await expect(page.locator('.message--assistant .message__status')).toHaveText('Przerwano');
    await expect(page.locator('#send')).toBeVisible();
});

test('done without a turn is ignored', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'done', stop_reason: 'cancelled'});
    await expect(page.locator('.message')).toHaveCount(0);
});

test('error shows a message bubble with its kind and ends the turn', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('a');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, {type: 'text_delta', text: 'zaczęte'});
    await dispatch(page, {type: 'error', kind: 'crashed', message: 'Agent zakończył się: <b>boom</b>'});

    const error = page.locator('.message--error');
    await expect(error).toHaveCount(1);
    await expect(error).toHaveAttribute('data-kind', 'crashed');
    await expect(error).toHaveAttribute('role', 'alert');
    await expect(error.locator('.message__text')).toHaveText('Agent zakończył się: <b>boom</b>');
    await expect(error.locator('b')).toHaveCount(0);
    await expect(page.locator('.message--assistant')).toHaveText('zaczęte');
    await expect(page.locator('#send')).toBeVisible();
    await expect(page.locator('#stop')).toBeHidden();
});

test('error with an unexpected kind is labelled unknown', async ({page}) => {
    await startChat(page);
    await dispatch(page, {type: 'error', kind: '" onclick="x', message: 'm'});
    await expect(page.locator('.message--error')).toHaveAttribute('data-kind', 'unknown');
});

test('malformed and unknown events are ignored', async ({page}) => {
    await startChat(page);
    const results = await page.evaluate(() => [null, 'text', {}, {type: 1}, {type: 'nope'},
        {type: 'text_delta', text: 5}].map(e => window.aiPanel.dispatch(e)));
    expect(results.slice(0, 5)).toEqual([false, false, false, false, false]);
    await expect(page.locator('.message')).toHaveCount(0);
});

test('the prompt grows with its content up to 8 lines', async ({page}) => {
    await startChat(page);
    const prompt = page.locator('#prompt');
    const height = () => prompt.evaluate(node => node.getBoundingClientRect().height);
    const one = await height();

    await prompt.fill('1\n2\n3');
    const three = await height();
    expect(three).toBeGreaterThan(one);

    await prompt.fill('1\n2\n3\n4\n5\n6\n7\n8');
    const eight = await height();
    await prompt.fill(Array.from({length: 20}, (_, i) => String(i)).join('\n'));
    const twenty = await height();
    expect(eight).toBeGreaterThan(three);
    expect(twenty).toBeCloseTo(eight, 0);
    expect(await prompt.evaluate(node => getComputedStyle(node).overflowY)).toBe('auto');

    await prompt.press('Enter');
    expect(await height()).toBeCloseTo(one, 0);
});

// Scrolls like the user would and waits until the page has seen the scroll event.
function scrollTo(list, where) {
    return list.evaluate((node, edge) => new Promise(resolve => {
        node.addEventListener('scroll', () => resolve(), {once: true});
        node.scrollTop = edge === 'top' ? 0 : node.scrollHeight;
    }), where);
}

test('the list follows new content unless the user scrolled up', async ({page}) => {
    await page.setViewportSize({width: 400, height: 400});
    await startChat(page);
    const list = page.locator('#messages');
    const distanceFromBottom = () => list.evaluate(n => n.scrollHeight - n.scrollTop - n.clientHeight);
    const long = Array.from({length: 40}, (_, i) => `Akapit ${i}\n\n`).join('');

    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, {type: 'text_delta', text: long});
    await expect.poll(distanceFromBottom).toBeLessThanOrEqual(1);

    // The user scrolls up: new deltas must not move the view.
    await scrollTo(list, 'top');
    await dispatch(page, {type: 'text_delta', text: long});
    await expect(page.locator('.message--assistant p')).toHaveCount(80);
    expect(await list.evaluate(n => n.scrollTop)).toBe(0);

    // Back at the bottom: following resumes.
    await scrollTo(list, 'bottom');
    await dispatch(page, {type: 'text_delta', text: long});
    await expect(page.locator('.message--assistant p')).toHaveCount(120);
    await expect.poll(distanceFromBottom).toBeLessThanOrEqual(1);
});

test('conversation clears the list and ends a running turn (new chat)', async ({page}) => {
    await startChat(page);
    await page.locator('#prompt').fill('Pytanie');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, {type: 'text_delta', text: 'Część odpowiedzi'});
    await expect(page.locator('.message')).toHaveCount(2);

    await dispatch(page, {type: 'conversation', id: null, messages: []});
    await expect(page.locator('.message')).toHaveCount(0);
    await expect(page.locator('#send')).toBeVisible();
    await expect(page.locator('#stop')).toBeHidden();

    // The done of the dropped turn that may follow does not add anything.
    await dispatch(page, {type: 'done', stop_reason: 'cancelled'});
    await expect(page.locator('.message')).toHaveCount(0);

    await page.locator('#prompt').fill('Nowe');
    await page.locator('#prompt').press('Enter');
    expect((await sent(page)).at(-1)).toEqual({type: 'send', text: 'Nowe'});
});
