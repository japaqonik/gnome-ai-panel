// Header of app/ui/chat.js: agent selector, model selector from config_options and the mode
// badge (S4-T4, FR-12, FR-28).
import {test, expect} from '@playwright/test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const indexUrl = pathToFileURL(path.resolve(here, '../../app/ui/index.html')).href;
const mockBridge = path.join(here, 'mock-bridge.js');

const AGENTS = [
    {id: 'fake-echo', name: 'Fake Echo', type: 'acp'},
    {id: 'fake-models', name: 'Fake Models', type: 'acp'},
    {id: 'czat', name: 'Czat', type: 'api'},
];

const MODEL = {
    id: 'model', name: 'Model', category: 'model', type: 'select', currentValue: 'small',
    options: [{value: 'small', name: 'Small'}, {value: 'large', name: 'Large'}],
};

let pageErrors;

function dispatch(page, event) {
    return page.evaluate(obj => window.__bridge.dispatch(obj), event);
}

function posted(page, type) {
    return page.evaluate(t => window.__bridge.messages.filter(m => m.type === t), type);
}

async function init(page, current = 'fake-echo', agents = AGENTS) {
    await dispatch(page, {type: 'init', agents, current, config_errors: [], theme: 'light'});
    await expect(page.locator('#chat')).toBeVisible();
}

async function requestDump(page) {
    await dispatch(page, {type: 'request_dump'});
    return (await posted(page, 'dump')).at(-1).state;
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

// --- agent selector -------------------------------------------------------------------

test('select#agent lists the agents and shows the current one', async ({page}) => {
    await init(page, 'fake-models');
    const agent = page.locator('#agent');
    await expect(agent).toHaveAttribute('aria-label', 'Agent');
    await expect(agent.locator('option')).toHaveText(['Fake Echo', 'Fake Models', 'Czat']);
    await expect(agent).toHaveValue('fake-models');
});

test('changing the agent posts select_agent and init confirms it', async ({page}) => {
    await init(page);
    await page.locator('#agent').selectOption('fake-models');
    expect(await posted(page, 'select_agent')).toEqual([{type: 'select_agent', id: 'fake-models'}]);
    await dispatch(page, {type: 'conversation', id: null, messages: []});
    await init(page, 'fake-models');
    await expect(page.locator('#agent')).toHaveValue('fake-models');
    expect((await requestDump(page)).agent).toBe('fake-models');
});

test('a refused agent change is undone by the next init', async ({page}) => {
    await init(page);
    await page.locator('#agent').selectOption('czat');
    await init(page, 'fake-echo');
    await expect(page.locator('#agent')).toHaveValue('fake-echo');
});

test('agent names with markup are text', async ({page}) => {
    await init(page, 'x', [{id: 'x', name: '<b>bold</b>', type: 'acp'}]);
    await expect(page.locator('#agent option')).toHaveText('<b>bold</b>');
    await expect(page.locator('.chat-header b')).toHaveCount(0);
});

// --- mode badge -----------------------------------------------------------------------

test('badge depends on the agent type', async ({page}) => {
    const badge = page.locator('#mode-badge');
    await init(page, 'fake-echo');
    await expect(badge).toBeVisible();
    await expect(badge).toHaveText('Agent z narzędziami');
    await expect(badge).toHaveAttribute('data-mode', 'tools');
    const toolsColour = await badge.evaluate(node => getComputedStyle(node).backgroundColor);
    expect((await requestDump(page)).badge).toBe('tools');

    await init(page, 'czat');
    await expect(badge).toHaveText('Czysty czat');
    await expect(badge).toHaveAttribute('data-mode', 'chat');
    const chatColour = await badge.evaluate(node => getComputedStyle(node).backgroundColor);
    expect(chatColour).not.toBe(toolsColour);
    expect((await requestDump(page)).badge).toBe('chat');

    await init(page, 'odd', [{id: 'odd', name: 'Odd', type: 'something'}]);
    await expect(badge).toBeHidden();
    expect((await requestDump(page)).badge).toBeNull();
});

test('badge colours differ in the dark theme too', async ({page}) => {
    const badge = page.locator('#mode-badge');
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'fake-echo', theme: 'dark'});
    const tools = await badge.evaluate(node => getComputedStyle(node).backgroundColor);
    await dispatch(page, {type: 'init', agents: AGENTS, current: 'czat', theme: 'dark'});
    const chat = await badge.evaluate(node => getComputedStyle(node).backgroundColor);
    expect(chat).not.toBe(tools);
});

// --- model selector -------------------------------------------------------------------

test('without config_options #model is hidden', async ({page}) => {
    await init(page);
    await expect(page.locator('#model')).toBeHidden();
});

test('config_options without a model select keep #model hidden', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [
        {...MODEL, id: 'mode', category: 'mode'},
        {...MODEL, type: 'boolean'},
        {...MODEL, options: 'nope'},
    ]});
    await expect(page.locator('#model')).toBeHidden();
});

test('a model option shows #model with its values', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [{...MODEL, id: 'mode', category: 'mode'}, MODEL]});
    const model = page.locator('#model');
    await expect(model).toBeVisible();
    await expect(model).toHaveAttribute('aria-label', 'Model');
    await expect(model.locator('option')).toHaveText(['Small', 'Large']);
    await expect(model).toHaveValue('small');
});

test('changing the model posts set_option and waits for the answer', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    const model = page.locator('#model');
    await model.selectOption('large');
    expect(await posted(page, 'set_option')).toEqual([
        {type: 'set_option', config_id: 'model', value: 'large'},
    ]);
    await expect(model).toBeDisabled();
    await dispatch(page, {type: 'config_options', options: [{...MODEL, currentValue: 'large'}]});
    await expect(model).toBeEnabled();
    await expect(model).toHaveValue('large');
});

test('a failed change shows the value the agent kept', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    await page.locator('#model').selectOption('large');
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    await dispatch(page, {type: 'notice', kind: 'option_failed', text: 'Nie udało się'});
    await expect(page.locator('#model')).toHaveValue('small');
    await expect(page.locator('#model')).toBeEnabled();
    await expect(page.locator('.message--notice[data-kind="option_failed"]')).toHaveText('Nie udało się');
});

test('grouped values become optgroups', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [{
        ...MODEL, currentValue: 'opus',
        options: [
            {group: 'fast', name: 'Szybkie', options: [{value: 'haiku', name: 'Haiku'}]},
            {group: 'smart', name: 'Mądre', options: [
                {value: 'sonnet', name: 'Sonnet'}, {value: 'opus', name: 'Opus'}]},
            {group: 'empty', name: 'Pusta', options: []},
        ],
    }]});
    const model = page.locator('#model');
    await expect(model).toBeVisible();
    await expect(model.locator('optgroup')).toHaveCount(2);
    expect(await model.locator('optgroup').evaluateAll(groups => groups.map(g => g.label)))
        .toEqual(['Szybkie', 'Mądre']);
    await expect(model.locator('optgroup[label="Mądre"] option')).toHaveText(['Sonnet', 'Opus']);
    await expect(model).toHaveValue('opus');
    await model.selectOption('haiku');
    expect((await posted(page, 'set_option')).at(-1)).toEqual(
        {type: 'set_option', config_id: 'model', value: 'haiku'});
});

test('a current value the agent does not list is still shown', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [{...MODEL, currentValue: 'secret'}]});
    await expect(page.locator('#model')).toHaveValue('secret');
    await expect(page.locator('#model option')).toHaveCount(3);
});

test('model names with markup are text', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [{
        ...MODEL, options: [{value: 'small', name: '<img src=x onerror="window.__xss=1">'}]}]});
    await expect(page.locator('#model option')).toHaveText('<img src=x onerror="window.__xss=1">');
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
});

test('empty config_options and a new conversation hide #model', async ({page}) => {
    await init(page);
    const model = page.locator('#model');
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    await expect(model).toBeVisible();
    await dispatch(page, {type: 'config_options', options: []});
    await expect(model).toBeHidden();
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    await dispatch(page, {type: 'conversation', id: null, messages: []});
    await expect(model).toBeHidden();
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    await page.locator('#model').selectOption('large');
    await dispatch(page, {type: 'conversation', id: null, messages: []});
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    await expect(model).toBeEnabled();
});

test('the empty screen hides the header controls', async ({page}) => {
    await init(page);
    await dispatch(page, {type: 'config_options', options: [MODEL]});
    await dispatch(page, {type: 'init', agents: [], current: null, config_errors: []});
    await expect(page.locator('#empty-state')).toBeVisible();
    await expect(page.locator('#agent option')).toHaveCount(0);
    expect(await requestDump(page)).toMatchObject({agent: null, badge: null});
});
