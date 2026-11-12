// Chat screen: message list, prompt field, send/stop and the handlers of the events that
// Python dispatches during a turn (PLAN §12.2). Classic script loaded after strings.js and
// render.js; exposes window.aiPanelChat.create({post}) -> {dispatch(event)}.
//
// `init` also carries the theme ("light" | "dark", resolved by Python from chat.theme and the
// desktop) and chat.font_size; `request_dump` (debug only) is answered with `dump {state}`.
//
// Turn state: idle → (send) pending → (turn_start / text_delta) streaming → (done | error) idle.
// While not idle the stop button replaces send and Enter does not send.
//
// An assistant message holds, in this order: a collapsed <details class="thinking"> (only
// when thinking_delta arrived; header "Myśli…" while the agent thinks), the tool cards
// (.tools > .tool[data-tool-id][data-status], created by tool_call and updated by id through
// tool_update; updates of unknown ids are ignored) and the markdown body.
//
// permission_request goes to the modal dialog of permission.js (one request at a time, the
// rest queued); the dialog closes without answering on done, error, cancel and conversation.
//
// Stop marks the reply's unfinished tool cards (pending, in_progress) as cancelled at once;
// `done cancelled` does the same and adds the "Przerwano" marker. `error` shows a card with
// the title, message and hint Python sends (texts in app/strings.py), the agent's login
// methods (auth) and its stderr tail in a collapsed <details> (crashed). `error` with
// `blocked: true` disables the prompt and offers a "new conversation" button until the next
// `conversation`. `notice {kind, text}` is an info line placed before the running reply.
//
// Header (S4-T4): select#agent lists the agents of `init` (a change posts `select_agent
// {id}`; Python answers with `conversation` and `init`), #mode-badge shows the mode of the
// current agent ("tools" for acp, "chat" for api) and select#model is shown only while the
// last `config_options` holds a `select` option with category "model" (flat values or
// <optgroup>s). A model change posts `set_option {config_id, value}` and disables the select
// until the next `config_options`, which carries the value the agent really uses.
'use strict';

(function () {
    const strings = window.aiPanelStrings;
    const {renderMarkdown, enhanceCodeBlocks, formatInput} = window.aiPanelRender;

    const MAX_PROMPT_LINES = 8;
    // Distance from the bottom (px) within which the list keeps following new content.
    const STICKY_THRESHOLD_PX = 24;
    const ERROR_KIND = /^[a-z][a-z0-9_]{0,31}$/;
    const THEMES = ['light', 'dark'];
    // Same bounds as chat.font_size in app/config.py.
    const FONT_SIZE_MIN = 6;
    const FONT_SIZE_MAX = 72;
    // Plaque of the current agent's mode in the dump (PLAN §12.1): ACP agents have tools.
    const BADGES = Object.freeze({acp: 'tools', api: 'chat'});
    // ACP ToolCallStatus values; anything else leaves the card's status unchanged.
    const TOOL_STATUSES = Object.freeze(['pending', 'in_progress', 'completed', 'failed',
        'cancelled']);
    const MAX_TOOL_ID_LENGTH = 256;
    const UNFINISHED_TOOL_STATUSES = Object.freeze(['pending', 'in_progress']);
    const MAX_AUTH_METHODS = 20;

    function isToolId(value) {
        return typeof value === 'string' && value !== '' && value.length <= MAX_TOOL_ID_LENGTH;
    }

    function diffText(item) {
        const path = typeof item.path === 'string' ? item.path : '';
        const lines = [`--- ${path}`, `+++ ${path}`];
        if (typeof item.oldText === 'string')
            lines.push(...item.oldText.split('\n').map(line => `-${line}`));
        if (typeof item.newText === 'string')
            lines.push(...item.newText.split('\n').map(line => `+${line}`));
        return lines.join('\n');
    }

    // Fills `container` with the tool output (ACP ToolCallContent[]): text as rendered
    // markdown, diffs as <pre>, terminals by id. Returns whether anything was shown.
    function renderToolOutput(container, content) {
        container.replaceChildren();
        const items = Array.isArray(content) ? content : content == null ? [] : [content];
        const addMarkdown = text => {
            const part = document.createElement('div');
            part.className = 'tool__text';
            part.innerHTML = renderMarkdown(text);
            enhanceCodeBlocks(part);
            container.append(part);
        };
        const addPre = (className, text) => {
            const pre = document.createElement('pre');
            pre.className = className;
            pre.textContent = text;
            container.append(pre);
        };
        for (const item of items) {
            if (typeof item === 'string') {
                addMarkdown(item);
                continue;
            }
            if (item === null || typeof item !== 'object')
                continue;
            const block = item.type === 'content' ? item.content : item;
            if (block?.type === 'text' && typeof block.text === 'string')
                addMarkdown(block.text);
            else if (item.type === 'diff')
                addPre('tool__diff', diffText(item));
            else if (item.type === 'terminal')
                addPre('tool__terminal', `${strings.toolTerminal} ${String(item.terminalId ?? '')}`);
            else if (typeof block?.type === 'string')
                addPre('tool__other', `[${block.type.slice(0, 32)}]`);
        }
        return container.childNodes.length > 0;
    }

    function create({post}) {
        const el = {
            empty: document.getElementById('empty-state'),
            chat: document.getElementById('chat'),
            agent: document.getElementById('agent'),
            model: document.getElementById('model'),
            badge: document.getElementById('mode-badge'),
            messages: document.getElementById('messages'),
            composer: document.getElementById('composer'),
            prompt: document.getElementById('prompt'),
            send: document.getElementById('send'),
            stop: document.getElementById('stop'),
        };

        let busy = false;
        // The agent hit its restart limit: nothing can be sent until a new conversation.
        let blocked = false;
        // {id, type} of the agent named in the last `init`, or null.
        let currentAgent = null;
        // {id, currentValue} of the model option shown in select#model, or null.
        let modelOption = null;
        // Assistant message of the running turn: {node, body, buffer, frame, rendered}.
        let reply = null;
        let stickToBottom = true;

        const permission = window.aiPanelPermission.create({
            post,
            inert: [document.getElementById('app')],
            onClose() {
                if (!el.chat.hidden && !el.prompt.disabled)
                    el.prompt.focus();
            },
        });

        applyStrings();

        // --- layout helpers -------------------------------------------------------------

        function applyStrings() {
            el.messages.setAttribute('aria-label', strings.messagesLabel);
            el.prompt.setAttribute('aria-label', strings.promptLabel);
            el.prompt.placeholder = strings.promptPlaceholder;
            el.send.textContent = strings.send;
            el.send.setAttribute('aria-label', strings.sendLabel);
            el.stop.textContent = strings.stop;
            el.stop.setAttribute('aria-label', strings.stopLabel);
            el.agent.setAttribute('aria-label', strings.agentLabel);
            el.model.setAttribute('aria-label', strings.modelLabel);
        }

        function currentScreen() {
            return el.chat.hidden ? 'empty' : 'chat';
        }

        function applyTheme(theme) {
            const root = document.documentElement;
            if (THEMES.includes(theme))
                root.dataset.theme = theme;
            else
                delete root.dataset.theme; // follow prefers-color-scheme
            const light = document.getElementById('hljs-theme-light');
            const dark = document.getElementById('hljs-theme-dark');
            if (light && dark) {
                const forced = root.dataset.theme;
                light.disabled = forced === 'dark';
                dark.disabled = forced === 'light';
                dark.media = forced === 'dark' ? 'all' : '(prefers-color-scheme: dark)';
            }
        }

        function effectiveTheme() {
            const forced = document.documentElement.dataset.theme;
            if (THEMES.includes(forced))
                return forced;
            return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }

        function applyFontSize(size) {
            if (typeof size !== 'number' || !Number.isFinite(size))
                return;
            const px = Math.min(Math.max(Math.round(size), FONT_SIZE_MIN), FONT_SIZE_MAX);
            document.documentElement.style.setProperty('--font-size', `${px}px`);
        }

        function showScreen(name) {
            el.empty.hidden = name !== 'empty';
            el.chat.hidden = name !== 'chat';
        }

        function isNearBottom() {
            const list = el.messages;
            return list.scrollHeight - list.scrollTop - list.clientHeight <= STICKY_THRESHOLD_PX;
        }

        function followBottom() {
            if (stickToBottom)
                el.messages.scrollTop = el.messages.scrollHeight;
        }

        function resizePrompt() {
            const field = el.prompt;
            const style = getComputedStyle(field);
            const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
            const extra = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) +
                parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
            const max = line * MAX_PROMPT_LINES + extra;
            field.style.height = 'auto';
            const wanted = field.scrollHeight + parseFloat(style.borderTopWidth) +
                parseFloat(style.borderBottomWidth);
            field.style.height = `${Math.min(wanted, max)}px`;
            field.style.overflowY = wanted > max ? 'auto' : 'hidden';
        }

        function setBusy(value) {
            busy = value;
            el.send.hidden = value;
            el.stop.hidden = !value;
            el.stop.disabled = false;
            el.messages.setAttribute('aria-busy', String(value));
            if (!value && document.activeElement === el.stop)
                el.prompt.focus();
        }

        function setBlocked(value) {
            blocked = value;
            el.prompt.disabled = value;
            el.send.disabled = value;
            el.composer.dataset.blocked = String(value);
        }

        function appendMessage(role) {
            const node = document.createElement('article');
            node.className = `message message--${role}`;
            node.dataset.role = role;
            const body = document.createElement('div');
            body.className = 'message__body';
            node.append(body);
            el.messages.append(node);
            return {node, body};
        }

        // --- user actions ---------------------------------------------------------------

        function submit() {
            if (busy || blocked)
                return;
            const text = el.prompt.value;
            if (text.trim() === '')
                return;
            const {body} = appendMessage('user');
            body.textContent = text;
            el.prompt.value = '';
            resizePrompt();
            stickToBottom = true;
            followBottom();
            setBusy(true);
            post({type: 'send', text});
        }

        function cancel() {
            if (!busy)
                return;
            // The backend answers the open requests of a cancelled turn (ACP: cancelled).
            permission.closeAll();
            cancelTools(reply);
            // One cancel per turn; the button comes back with the next turn.
            el.stop.disabled = true;
            post({type: 'cancel'});
        }

        el.prompt.addEventListener('keydown', event => {
            if (event.key !== 'Enter' || event.shiftKey || event.isComposing)
                return;
            // Plain Enter never inserts a newline; it sends unless a turn is running.
            event.preventDefault();
            submit();
        });
        el.prompt.addEventListener('input', resizePrompt);
        el.composer.addEventListener('submit', event => {
            event.preventDefault();
            submit();
        });
        el.stop.addEventListener('click', cancel);
        el.messages.addEventListener('scroll', () => {
            stickToBottom = isNearBottom();
        });

        // --- streamed reply -------------------------------------------------------------

        function startReply() {
            if (!reply) {
                const {node, body} = appendMessage('assistant');
                reply = {
                    node, body, buffer: '', frame: 0, rendered: '',
                    thinking: null, toolList: null, tools: new Map(),
                };
                followBottom();
            }
            return reply;
        }

        function renderReply(target) {
            target.frame = 0;
            if (target.rendered === target.buffer)
                return;
            target.rendered = target.buffer;
            target.body.innerHTML = renderMarkdown(target.buffer);
            enhanceCodeBlocks(target.body);
            followBottom();
        }

        function scheduleRender(target) {
            // At most one render per frame however many deltas arrive (NFR-1).
            if (!target.frame)
                target.frame = requestAnimationFrame(() => renderReply(target));
        }

        // Renders what is buffered now and detaches the reply from the turn.
        function finishReply() {
            const target = reply;
            reply = null;
            if (!target)
                return null;
            if (target.frame)
                cancelAnimationFrame(target.frame);
            renderReply(target);
            endThinking(target);
            return target;
        }

        // --- thinking block -------------------------------------------------------------

        function setThinkingActive(thinking, active) {
            thinking.details.dataset.state = active ? 'active' : 'done';
            thinking.summary.textContent = active ? strings.thinkingActive : strings.thinkingDone;
        }

        function endThinking(target) {
            if (target?.thinking)
                setThinkingActive(target.thinking, false);
        }

        function ensureThinking(target) {
            if (!target.thinking) {
                // Collapsed by default (no `open`); the user may expand it.
                const details = document.createElement('details');
                details.className = 'thinking';
                const summary = document.createElement('summary');
                summary.className = 'thinking__summary';
                const text = document.createElement('div');
                text.className = 'thinking__body';
                details.append(summary, text);
                target.node.insertBefore(details, target.toolList ?? target.body);
                target.thinking = {details, summary, body: text};
            }
            return target.thinking;
        }

        // --- tool cards -----------------------------------------------------------------

        function createToolCard(id) {
            const card = document.createElement('article');
            card.className = 'tool';
            card.dataset.toolId = id;
            const header = document.createElement('div');
            header.className = 'tool__header';
            const icon = document.createElement('span');
            icon.className = 'tool__icon';
            icon.setAttribute('aria-hidden', 'true');
            const title = document.createElement('span');
            title.className = 'tool__title';
            const status = document.createElement('span');
            status.className = 'tool__status';
            header.append(icon, title, status);

            const section = (className, label, contentTag) => {
                const details = document.createElement('details');
                details.className = `tool__section ${className}`;
                details.hidden = true;
                const summary = document.createElement('summary');
                summary.textContent = label;
                const content = document.createElement(contentTag);
                content.className = 'tool__content';
                details.append(summary, content);
                return {details, content};
            };
            const input = section('tool__input', strings.toolInput, 'pre');
            const output = section('tool__output', strings.toolOutput, 'div');
            card.append(header, input.details, output.details);
            return {card, title, status, input, output};
        }

        function setToolStatus(tool, status) {
            if (!TOOL_STATUSES.includes(status))
                return;
            tool.card.dataset.status = status;
            tool.status.textContent = strings.toolStatus[status];
        }

        function setToolTitle(tool, title) {
            tool.title.textContent = typeof title === 'string' && title !== ''
                ? title : strings.toolUntitled;
        }

        function setToolInput(tool, value) {
            const text = formatInput(value);
            tool.input.content.textContent = text;
            tool.input.details.hidden = text === '';
        }

        function setToolOutput(tool, content) {
            tool.output.details.hidden = !renderToolOutput(tool.output.content, content);
        }

        function ensureToolList(target) {
            if (!target.toolList) {
                const list = document.createElement('div');
                list.className = 'tools';
                target.node.insertBefore(list, target.body);
                target.toolList = list;
            }
            return target.toolList;
        }

        function cancelTools(target) {
            for (const tool of target?.tools.values() ?? []) {
                if (UNFINISHED_TOOL_STATUSES.includes(tool.card.dataset.status))
                    setToolStatus(tool, 'cancelled');
            }
        }

        function addStatus(node, reason, text) {
            const status = document.createElement('p');
            status.className = 'message__status';
            status.dataset.status = reason;
            status.textContent = text;
            node.append(status);
        }

        // --- header: agent, model, mode badge -------------------------------------------

        function setBadge(type) {
            const mode = Object.hasOwn(BADGES, type ?? '') ? BADGES[type] : null;
            el.badge.hidden = mode === null;
            if (mode === null) {
                delete el.badge.dataset.mode;
                el.badge.textContent = '';
                el.badge.removeAttribute('title');
                return;
            }
            el.badge.dataset.mode = mode;
            el.badge.textContent = strings.badges[mode];
            el.badge.title = strings.badgeTitles[mode];
        }

        function fillAgents(agents, current) {
            el.agent.replaceChildren();
            for (const agent of agents) {
                const option = document.createElement('option');
                option.value = agent.id;
                option.textContent = agent.name;
                el.agent.append(option);
            }
            el.agent.value = current.id;
        }

        function textOrNull(value) {
            return typeof value === 'string' && value !== '' ? value : null;
        }

        function selectOption(item) {
            const option = document.createElement('option');
            option.value = item.value;
            option.textContent = textOrNull(item.name) ?? item.value;
            if (textOrNull(item.description))
                option.title = item.description;
            return option;
        }

        const isSelectValue = item => typeof item?.value === 'string' && item.value !== '';

        // The first select option with category "model" (ACP SessionConfigOption).
        function findModelOption(options) {
            if (!Array.isArray(options))
                return null;
            return options.find(option => option !== null && typeof option === 'object' &&
                option.category === 'model' && option.type === 'select' &&
                typeof option.id === 'string' && option.id !== '' &&
                typeof option.currentValue === 'string' && Array.isArray(option.options)) ??
                null;
        }

        function hideModel() {
            modelOption = null;
            el.model.replaceChildren();
            el.model.hidden = true;
            el.model.disabled = false;
        }

        function showModel(option) {
            const children = [];
            for (const item of option.options) {
                if (Array.isArray(item?.options)) {
                    const values = item.options.filter(isSelectValue);
                    if (values.length === 0)
                        continue;
                    const group = document.createElement('optgroup');
                    group.label = textOrNull(item.name) ?? String(item.group ?? '');
                    group.append(...values.map(selectOption));
                    children.push(group);
                } else if (isSelectValue(item)) {
                    children.push(selectOption(item));
                }
            }
            if (children.length === 0) {
                hideModel();
                return;
            }
            el.model.replaceChildren(...children);
            const known = [...el.model.options].some(o => o.value === option.currentValue);
            if (!known) {
                // The agent uses a value it does not list: show it rather than a wrong one.
                el.model.prepend(selectOption({value: option.currentValue}));
            }
            el.model.value = option.currentValue;
            el.model.title = textOrNull(option.name) ?? strings.modelLabel;
            modelOption = {id: option.id, currentValue: option.currentValue};
            el.model.disabled = false;
            el.model.hidden = false;
        }

        function onConfigOptions(event) {
            const option = findModelOption(event.options);
            if (option)
                showModel(option);
            else
                hideModel();
        }

        el.agent.addEventListener('change', () => {
            const id = el.agent.value;
            if (!currentAgent || id === currentAgent.id)
                return;
            // Python starts a new conversation and confirms the agent with `init`.
            post({type: 'select_agent', id});
        });

        el.model.addEventListener('change', () => {
            if (!modelOption || el.model.value === modelOption.currentValue)
                return;
            el.model.disabled = true;
            post({type: 'set_option', config_id: modelOption.id, value: el.model.value});
        });

        // --- dispatch handlers ----------------------------------------------------------

        function onInit(event) {
            applyTheme(event.theme);
            applyFontSize(event.font_size);
            const agents = (Array.isArray(event.agents) ? event.agents : [])
                .filter(agent => typeof agent?.id === 'string' && agent.id !== '')
                .map(agent => ({
                    id: agent.id,
                    name: textOrNull(agent.name) ?? agent.id,
                    type: typeof agent.type === 'string' ? agent.type : null,
                }));
            if (agents.length === 0) {
                currentAgent = null;
                el.agent.replaceChildren();
                setBadge(null);
                hideModel();
                showScreen('empty');
                return;
            }
            const current = agents.find(agent => agent.id === event.current) ?? agents[0];
            currentAgent = {id: current.id, type: current.type};
            fillAgents(agents, current);
            setBadge(current.type);
            const wasHidden = el.chat.hidden;
            showScreen('chat');
            if (wasHidden) {
                resizePrompt();
                el.prompt.focus();
            }
        }

        function onTurnStart() {
            finishReply();
            setBusy(true);
            startReply();
        }

        function onTextDelta(event) {
            if (typeof event.text !== 'string' || event.text === '')
                return;
            if (!busy)
                setBusy(true);
            const target = startReply();
            endThinking(target);
            target.buffer += event.text;
            scheduleRender(target);
        }

        function onThinkingDelta(event) {
            if (typeof event.text !== 'string' || event.text === '')
                return;
            if (!busy)
                setBusy(true);
            const thinking = ensureThinking(startReply());
            setThinkingActive(thinking, true);
            thinking.body.append(event.text);
            followBottom();
        }

        function onToolCall(event) {
            if (!isToolId(event.id))
                return;
            if (!busy)
                setBusy(true);
            const target = startReply();
            endThinking(target);
            let tool = target.tools.get(event.id);
            if (!tool) {
                tool = createToolCard(event.id);
                target.tools.set(event.id, tool);
                ensureToolList(target).append(tool.card);
            }
            // A repeated tool_call with a known id describes the same call again.
            if (typeof event.kind === 'string' && event.kind !== '')
                tool.card.dataset.kind = event.kind.slice(0, 32);
            setToolTitle(tool, event.title);
            if (TOOL_STATUSES.includes(event.status))
                setToolStatus(tool, event.status);
            else if (!tool.card.dataset.status)
                setToolStatus(tool, 'pending');
            setToolInput(tool, event.raw_input);
            setToolOutput(tool, event.content);
            followBottom();
        }

        // Only the fields present (and not null) change; unknown ids are ignored.
        function onToolUpdate(event) {
            if (!isToolId(event.id))
                return;
            const tool = reply?.tools.get(event.id);
            if (!tool)
                return;
            if (event.status != null)
                setToolStatus(tool, event.status);
            if (event.title != null)
                setToolTitle(tool, event.title);
            if (event.raw_input != null)
                setToolInput(tool, event.raw_input);
            if (event.content != null)
                setToolOutput(tool, event.content);
            followBottom();
        }

        function onPermissionRequest(event) {
            // Only the running turn may ask; a late request has already been answered.
            if (!busy)
                return;
            permission.request(event);
        }

        function onDone(event) {
            permission.closeAll();
            if (!busy && !reply)
                return;
            const reason = typeof event.stop_reason === 'string' ? event.stop_reason : 'end_turn';
            let target = finishReply();
            if (reason === 'cancelled')
                cancelTools(target);
            const marker = Object.hasOwn(strings.stopReasons, reason)
                ? strings.stopReasons[reason] : null;
            if (marker) {
                target ??= {node: appendMessage('assistant').node};
                addStatus(target.node, reason, marker);
            }
            setBusy(false);
            followBottom();
        }

        function textOf(value) {
            return typeof value === 'string' && value !== '' ? value : null;
        }

        function appendText(parent, tag, className, text) {
            const node = document.createElement(tag);
            node.className = className;
            node.textContent = text;
            parent.append(node);
            return node;
        }

        // An empty reply (the turn failed before the agent said anything) is removed.
        function dropEmptyReply(target) {
            if (target && target.buffer === '' && !target.thinking && target.tools.size === 0)
                target.node.remove();
        }

        function onError(event) {
            permission.closeAll();
            dropEmptyReply(finishReply());
            const kind = typeof event.kind === 'string' && ERROR_KIND.test(event.kind)
                ? event.kind : 'unknown';
            const {node, body} = appendMessage('error');
            node.dataset.kind = kind;
            node.setAttribute('role', 'alert');
            // Every field goes in as text: messages and stderr come from the agent.
            appendText(body, 'strong', 'message__title', textOf(event.title) ?? strings.errorTitle);
            appendText(body, 'p', 'message__text', textOf(event.message) ?? strings.errorTitle);
            if (Array.isArray(event.auth_methods)) {
                const label = textOf(event.methods_label);
                if (label)
                    appendText(body, 'p', 'message__label', label);
                const methods = event.auth_methods.filter(textOf).slice(0, MAX_AUTH_METHODS);
                if (methods.length > 0) {
                    const list = document.createElement('ul');
                    list.className = 'message__methods';
                    for (const method of methods)
                        appendText(list, 'li', 'message__method', method);
                    body.append(list);
                }
            }
            const stderr = textOf(event.stderr);
            if (stderr) {
                const details = document.createElement('details');
                details.className = 'message__stderr';
                appendText(details, 'summary', 'message__stderr-label',
                    textOf(event.stderr_label) ?? strings.stderrLabel);
                appendText(details, 'pre', 'message__stderr-text', stderr);
                body.append(details);
            }
            const hint = textOf(event.hint);
            if (hint)
                appendText(body, 'p', 'message__hint', hint);
            if (event.blocked === true) {
                const button = appendText(body, 'button', 'button button--primary message__action',
                    strings.newChat);
                button.type = 'button';
                button.dataset.action = 'new-chat';
                button.addEventListener('click', () => post({type: 'new_chat'}));
                setBlocked(true);
            }
            setBusy(false);
            followBottom();
        }

        function onNotice(event) {
            const text = textOf(event.text);
            if (!text)
                return;
            const node = document.createElement('p');
            node.className = 'message message--notice';
            node.dataset.role = 'notice';
            if (typeof event.kind === 'string' && ERROR_KIND.test(event.kind))
                node.dataset.kind = event.kind;
            node.setAttribute('role', 'status');
            node.textContent = text;
            // Before the reply of the running turn, so it reads in the right order.
            if (reply?.node.isConnected)
                el.messages.insertBefore(node, reply.node);
            else
                el.messages.append(node);
            followBottom();
        }

        // A new (empty) conversation: clears the list. Messages of a stored conversation
        // are shown when the history arrives (later stage); for now only the reset.
        function onConversation() {
            permission.closeAll();
            const target = reply;
            reply = null;
            if (target?.frame)
                cancelAnimationFrame(target.frame);
            el.messages.replaceChildren();
            // The options belong to the session; a new one reports its own.
            hideModel();
            setBusy(false);
            setBlocked(false);
            stickToBottom = true;
        }

        // --- debug dump (PLAN §12.1) -----------------------------------------------------

        function messageText(node) {
            const copy = node.cloneNode(true);
            for (const extra of copy.querySelectorAll(
                '.code-block__bar, :scope > .thinking, :scope > .tools'))
                extra.remove();
            return copy.textContent;
        }

        function messageTools(node) {
            return [...node.querySelectorAll(':scope > .tools > .tool')].map(card => ({
                id: card.dataset.toolId ?? null,
                title: card.querySelector('.tool__title')?.textContent ?? '',
                status: card.dataset.status ?? null,
            }));
        }

        function collectState() {
            const messages = [...el.messages.querySelectorAll(':scope > .message')].map(node => ({
                role: node.dataset.role ?? null,
                text: messageText(node),
                html: node.querySelector(':scope > .message__body')?.innerHTML ?? '',
                thinking: node.querySelector(':scope > .thinking > .thinking__body')
                    ?.textContent ?? '',
                tools: messageTools(node),
                ...(node.dataset.kind ? {kind: node.dataset.kind} : {}),
            }));
            return {
                screen: currentScreen(),
                agent: currentAgent?.id ?? null,
                badge: Object.hasOwn(BADGES, currentAgent?.type ?? '')
                    ? BADGES[currentAgent.type] : null,
                messages,
                permission_dialog: permission.state(),
                banner: null,
                theme: effectiveTheme(),
                busy,
            };
        }

        function onRequestDump() {
            post({type: 'dump', state: collectState()});
        }

        const handlers = {
            init: onInit,
            request_dump: onRequestDump,
            conversation: onConversation,
            turn_start: onTurnStart,
            text_delta: onTextDelta,
            thinking_delta: onThinkingDelta,
            tool_call: onToolCall,
            tool_update: onToolUpdate,
            permission_request: onPermissionRequest,
            notice: onNotice,
            config_options: onConfigOptions,
            done: onDone,
            error: onError,
        };

        function dispatch(event) {
            if (event === null || typeof event !== 'object' || typeof event.type !== 'string')
                return false;
            const handler = Object.hasOwn(handlers, event.type) ? handlers[event.type] : null;
            if (!handler)
                return false; // Events of later stages (usage, …) are ignored.
            handler(event);
            return true;
        }

        return Object.freeze({dispatch});
    }

    window.aiPanelChat = Object.freeze({create});
})();
