// Edge cases of the permission dialog (S4-T2, FR-11), added by the tester.
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

const AGENTS = [{id: 'fake-perm', name: 'Fake Perm', type: 'acp'}];
const OPTIONS = [
    {id: 'allow', name: 'Zezwól', kind: 'allow_once'},
    {id: 'reject', name: 'Odrzuć', kind: 'reject_once'},
];

let pageErrors;

function dispatch(page, event) {
    return page.evaluate(obj => window.__bridge.dispatch(obj), event);
}

function posted(page, type) {
    return page.evaluate(t => window.__bridge.messages.filter(m => m.type === t), type);
}

async function startTurn(page) {
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'fake-perm', config_errors: []});
    await expect(page.locator('#chat')).toBeVisible();
    await page.locator('#prompt').fill('zrób');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
}

function permissionRequest(extra = {}) {
    return {
        type: 'permission_request', request_id: 'perm-1', tool_call_id: 'call_perm',
        title: 'Zapis pliku out.txt', kind: 'edit',
        raw_input: {path: 'out.txt', content: 'x'}, options: OPTIONS, ...extra,
    };
}

const dialog = page => page.getByRole('dialog');

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

test('Enter right after the dialog opens rejects (default focus is safe)', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await page.keyboard.press('Enter');
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'reject'},
    ]);
    // The prompt was not sent a second time by that Enter.
    expect(await posted(page, 'send')).toHaveLength(1);
});

test('Esc with the focus on the input block still rejects', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await page.locator('#permission-input').focus();
    await page.keyboard.press('Escape');
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'reject'},
    ]);
    await expect(dialog(page)).toBeHidden();
});

test('typing while the dialog is open does not reach the prompt', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await page.keyboard.type('abc');
    await expect(page.locator('#prompt')).toHaveValue('');
    expect(await posted(page, 'permission')).toEqual([]);
});

test('Esc on the last answered request does nothing more', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    expect(await posted(page, 'permission')).toHaveLength(1);
});

test('a request arriving after done is ignored', async ({page}) => {
    await startTurn(page);
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await dispatch(page, permissionRequest());
    await expect(dialog(page)).toBeHidden();
});

test('a request id answered earlier in the turn can open again only once', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await page.locator('[data-option-kind=reject_once]').click();
    // A different request of the same turn opens normally afterwards.
    await dispatch(page, permissionRequest({request_id: 'perm-2'}));
    await expect(dialog(page)).toBeVisible();
    await expect(page.locator('[data-option-kind=reject_once]')).toBeFocused();
});

test('Esc with an empty option list answers null through the fallback', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest({options: []}));
    await expect(page.locator('#permission-options button')).toHaveText(['Odrzuć']);
    await page.keyboard.press('Escape');
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: null},
    ]);
});

test('a double click on allow does not also allow the queued request', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await dispatch(page, permissionRequest({request_id: 'perm-2', title: 'rm -rf build'}));
    await page.locator('[data-option-kind=allow_once]').dblclick();
    const answers = await posted(page, 'permission');
    expect(answers[0]).toEqual({type: 'permission', request_id: 'perm-1', option_id: 'allow'});
    // The second click must not silently answer perm-2 with "allow".
    expect(answers.filter(a => a.request_id === 'perm-2' && a.option_id === 'allow'))
        .toEqual([]);
});

// Attempt 2 (tester): the pointer guard added for the double-click fix.

test('a triple click answers only the first of three queued requests', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await dispatch(page, permissionRequest({request_id: 'perm-2', title: 'drugi'}));
    await dispatch(page, permissionRequest({request_id: 'perm-3', title: 'trzeci'}));
    // Playwright waits until aria-disabled is gone (the guard has ended) before clicking.
    await page.locator('[data-option-kind=allow_once]').click({clickCount: 3});
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'allow'},
    ]);
    await expect(page.locator('#permission-title')).toHaveText('drugi');
});

test('two quick separate single clicks do not answer the next request', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await dispatch(page, permissionRequest({request_id: 'perm-2', title: 'drugi'}));
    const allow = page.locator('[data-option-kind=allow_once]');
    await expect(allow).not.toHaveAttribute('aria-disabled', 'true');
    const box = await allow.boundingBox();
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    // Two independent clicks (detail 1 each), the second lands on the new request's button.
    await page.mouse.click(x, y);
    await page.mouse.click(x, y);
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'allow'},
    ]);
    await expect(page.locator('#permission-title')).toHaveText('drugi');
    await expect(allow).toHaveAttribute('aria-disabled', 'true');
});

test('Esc works at once during the pointer guard', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await expect(page.locator('[data-option-kind=allow_once]'))
        .toHaveAttribute('aria-disabled', 'true');
    await page.keyboard.press('Escape');
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'reject'},
    ]);
});

test('closing during the guard leaves no stale timer for the next turn', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await dispatch(page, {type: 'done', stop_reason: 'end_turn'});
    await expect(dialog(page)).toBeHidden();
    await page.locator('#prompt').fill('znowu');
    await page.locator('#prompt').press('Enter');
    await dispatch(page, {type: 'turn_start'});
    await dispatch(page, permissionRequest({request_id: 'perm-9'}));
    const allow = page.locator('[data-option-kind=allow_once]');
    // The new request is guarded again and a click after the guard counts.
    await expect(allow).toHaveAttribute('aria-disabled', 'true');
    await allow.click();
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-9', option_id: 'allow'},
    ]);
});
