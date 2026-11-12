// Permission dialog of app/ui/permission.js and chat.js (S4-T2, FR-11, NFR-3).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

const AGENTS = [{id: 'fake-perm', name: 'Fake Perm', type: 'acp'}];
const OPTIONS = [
    {id: 'allow', name: 'Zezwól', kind: 'allow_once'},
    {id: 'allow-all', name: 'Zezwól zawsze', kind: 'allow_always'},
    {id: 'reject', name: 'Odrzuć', kind: 'reject_once'},
];

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

test('the request opens a modal dialog with focus on the reject button', async ({page}) => {
    await startTurn(page);
    await expect(dialog(page)).toBeHidden();
    expect(await dispatch(page, permissionRequest())).toBe(true);

    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toHaveAttribute('aria-modal', 'true');
    await expect(dialog(page)).toHaveAccessibleName('Agent prosi o zgodę');
    await expect(page.locator('#permission-title')).toHaveText('Zapis pliku out.txt');
    await expect(page.locator('#permission-kind')).toHaveText('Rodzaj: Edycja');
    await expect(page.locator('#permission-input'))
        .toHaveText(JSON.stringify({path: 'out.txt', content: 'x'}, null, 2));

    const buttons = page.locator('#permission-options button');
    await expect(buttons).toHaveText(['Zezwól', 'Zezwól zawsze', 'Odrzuć']);
    await expect(page.locator('[data-option-kind=allow_once]')).toHaveAttribute(
        'data-option-id', 'allow');
    await expect(page.locator('[data-option-kind=reject_once]')).toBeFocused();
    // The rest of the page is inert while the dialog is open.
    await expect(page.locator('#app')).toHaveAttribute('inert', '');

    const state = await requestDump(page);
    expect(state.permission_dialog).toEqual({open: true, title: 'Zapis pliku out.txt'});
    // Nothing was answered on the user's behalf.
    expect(await posted(page, 'permission')).toEqual([]);
});

test('a click on an option posts it and closes the dialog', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await page.locator('[data-option-kind=allow_once]').click();
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'allow'},
    ]);
    await expect(dialog(page)).toBeHidden();
    await expect(page.locator('#app')).not.toHaveAttribute('inert', /.*/);
    await expect(page.locator('#prompt')).toBeFocused();
    expect((await requestDump(page)).permission_dialog).toEqual({open: false, title: ''});
    // Still busy: the turn goes on until `done`.
    await expect(page.locator('#stop')).toBeVisible();
});

test('Esc answers with the reject_once option', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest({options: [
        {id: 'never', name: 'Odrzuć zawsze', kind: 'reject_always'},
        ...OPTIONS,
    ]}));
    await expect(page.locator('[data-option-kind=reject_once]')).toBeFocused();
    await page.keyboard.press('Escape');
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'reject'},
    ]);
    await expect(dialog(page)).toBeHidden();
});

test('Esc without a reject_once option answers null', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest({options: [
        {id: 'allow', name: 'Zezwól', kind: 'allow_once'},
        {id: 'never', name: 'Nigdy', kind: 'reject_always'},
    ]}));
    // reject_always is the only way to say no, so it gets the focus; Esc stays non-permanent.
    await expect(page.locator('[data-option-kind=reject_always]')).toBeFocused();
    await page.keyboard.press('Escape');
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: null},
    ]);
});

test('without reject options a fallback reject button answers null', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest({options: [
        {id: 'allow', name: 'Zezwól', kind: 'allow_once'},
    ]}));
    const fallback = page.locator('.permission__option--fallback');
    await expect(fallback).toHaveText('Odrzuć');
    await expect(fallback).toBeFocused();
    await fallback.press('Enter');
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: null},
    ]);
});

test('two requests: the second appears after the first is answered', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await dispatch(page, permissionRequest({
        request_id: 'perm-2', title: 'Polecenie rm -rf build', kind: 'execute',
        raw_input: 'rm -rf build',
    }));
    await dispatch(page, permissionRequest()); // repeated id: ignored
    await expect(page.locator('#permission-title')).toHaveText('Zapis pliku out.txt');
    await expect(page.locator('#permission-queue')).toHaveText('Oczekujące prośby: 1');
    await expect(dialog(page)).toHaveCount(1);

    await page.locator('[data-option-kind=reject_once]').click();
    await expect(page.locator('#permission-title')).toHaveText('Polecenie rm -rf build');
    await expect(page.locator('#permission-kind')).toHaveText('Rodzaj: Wykonanie polecenia');
    await expect(page.locator('#permission-input')).toHaveText('rm -rf build');
    await expect(page.locator('#permission-queue')).toBeHidden();
    await expect(page.locator('[data-option-kind=reject_once]')).toBeFocused();
    expect((await requestDump(page)).permission_dialog.title).toBe('Polecenie rm -rf build');

    await page.locator('[data-option-kind=allow_once]').click();
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'reject'},
        {type: 'permission', request_id: 'perm-2', option_id: 'allow'},
    ]);
    await expect(dialog(page)).toBeHidden();
});

for (const [name, event] of [
    ['done', {type: 'done', stop_reason: 'cancelled'}],
    ['error', {type: 'error', message: 'boom', kind: 'crashed'}],
    ['conversation', {type: 'conversation', id: null, messages: []}],
]) {
    test(`${name} closes the dialog and drops the queue without answering`, async ({page}) => {
        await startTurn(page);
        await dispatch(page, permissionRequest());
        await dispatch(page, permissionRequest({request_id: 'perm-2'}));
        await expect(dialog(page)).toBeVisible();
        await dispatch(page, event);
        await expect(dialog(page)).toBeHidden();
        await expect(page.locator('#app')).not.toHaveAttribute('inert', /.*/);
        expect(await posted(page, 'permission')).toEqual([]);
        expect((await requestDump(page)).permission_dialog).toEqual({open: false, title: ''});
    });
}

test('cancel closes the dialog and posts only cancel', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    // The stop button is behind the modal; the debug action clicks it programmatically.
    await page.evaluate(() => document.getElementById('stop').click());
    await expect(dialog(page)).toBeHidden();
    expect(await posted(page, 'cancel')).toHaveLength(1);
    expect(await posted(page, 'permission')).toEqual([]);
});

test('title, kind, input and option names are shown as text', async ({page}) => {
    await startTurn(page);
    const html = '<img src=x onerror="window.__xss = 1"><b>x</b>';
    await dispatch(page, permissionRequest({
        title: html, kind: html, raw_input: {command: html},
        options: [
            {id: 'a', name: html, kind: 'allow_once'},
            {id: 'r', name: 'Odrzuć', kind: 'reject_once'},
        ],
    }));
    await expect(page.locator('#permission-title')).toHaveText(html);
    await expect(page.locator('[data-option-id=a]')).toHaveText(html);
    await expect(page.locator('#permission-input')).toContainText(JSON.stringify(html));
    expect(await page.locator('#permission-dialog img, #permission-dialog b').count()).toBe(0);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
});

test('a long command is shown in full', async ({page}) => {
    await startTurn(page);
    const command = `bash -c '${'echo segment; '.repeat(200)}rm -rf ~/very/important/path'`;
    await dispatch(page, permissionRequest({kind: 'execute', raw_input: {command}}));
    const text = await page.locator('#permission-input').textContent();
    expect(text).toContain(command);
    // Wrapped, not clipped horizontally.
    const overflow = await page.locator('#permission-input').evaluate(
        node => node.scrollWidth - node.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
});

test('Tab keeps the focus inside the dialog', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    const inDialog = () => page.evaluate(
        () => document.getElementById('permission-dialog').contains(document.activeElement));
    for (let i = 0; i < 6; i++) {
        await page.keyboard.press('Tab');
        expect(await inDialog()).toBe(true);
    }
    for (let i = 0; i < 6; i++) {
        await page.keyboard.press('Shift+Tab');
        expect(await inDialog()).toBe(true);
    }
    expect(await posted(page, 'permission')).toEqual([]);
});

test('invalid requests and requests outside a turn are ignored', async ({page}) => {
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'fake-perm', config_errors: []});
    await dispatch(page, permissionRequest()); // no turn running
    await expect(dialog(page)).toBeHidden();
    await startTurn(page);
    for (const bad of [{request_id: ''}, {request_id: 7}, {request_id: 'x'.repeat(257)}])
        await dispatch(page, permissionRequest(bad));
    await expect(dialog(page)).toBeHidden();
    // Malformed options are skipped, a missing name falls back to the kind's label.
    await dispatch(page, permissionRequest({
        title: '', raw_input: null,
        options: [null, 5, {id: ''}, {id: 'allow', kind: 'allow_once'}, {id: 'allow', name: 'x'},
            {id: 'r', name: '', kind: 'reject_once'}],
    }));
    await expect(page.locator('#permission-title')).toHaveText('Narzędzie');
    await expect(page.locator('#permission-input')).toHaveText('(brak danych wejściowych)');
    await expect(page.locator('#permission-options button')).toHaveText(['Zezwól', 'Odrzuć']);
});

test('pointer clicks right after a request is shown are ignored, keys are not', async ({page}) => {
    await startTurn(page);
    await dispatch(page, permissionRequest());
    await dispatch(page, permissionRequest({request_id: 'perm-2', title: 'rm -rf build'}));
    // A mouse click (detail 1) in the same task as the request: still guarded.
    await page.evaluate(() => {
        const button = document.querySelector('[data-option-kind=allow_once]');
        button.dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1}));
    });
    expect(await posted(page, 'permission')).toEqual([]);
    await expect(page.locator('[data-option-kind=allow_once]'))
        .toHaveAttribute('aria-disabled', 'true');

    // The keyboard answers immediately, and the next request is guarded again.
    await page.keyboard.press('Enter');
    await expect(page.locator('#permission-title')).toHaveText('rm -rf build');
    await page.evaluate(() => {
        const button = document.querySelector('[data-option-kind=allow_once]');
        button.dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1}));
    });
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'reject'},
    ]);

    // Once the guard expires a click counts.
    await expect(page.locator('[data-option-kind=allow_once]')).not.toHaveAttribute(
        'aria-disabled', 'true');
    await page.locator('[data-option-kind=allow_once]').click();
    expect(await posted(page, 'permission')).toEqual([
        {type: 'permission', request_id: 'perm-1', option_id: 'reject'},
        {type: 'permission', request_id: 'perm-2', option_id: 'allow'},
    ]);
});
