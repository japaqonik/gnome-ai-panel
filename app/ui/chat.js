// Chat screen: message list, prompt field, send/stop and the handlers of the events that
// Python dispatches during a turn (PLAN §12.2). Classic script loaded after strings.js and
// render.js; exposes window.aiPanelChat.create({post}) -> {dispatch(event)}.
//
// `init` also carries the theme ("light" | "dark", resolved by Python from chat.theme and the
// desktop) and chat.font_size; `request_dump` (debug only) is answered with `dump {state}`.
//
// Turn state: idle → (send) pending → (turn_start / text_delta) streaming → (done | error) idle.
// While not idle the stop button replaces send and Enter does not send.
'use strict';

(function () {
    const strings = window.aiPanelStrings;
    const {renderMarkdown, enhanceCodeBlocks} = window.aiPanelRender;

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

    function create({post}) {
        const el = {
            empty: document.getElementById('empty-state'),
            chat: document.getElementById('chat'),
            agentName: document.getElementById('agent-name'),
            messages: document.getElementById('messages'),
            composer: document.getElementById('composer'),
            prompt: document.getElementById('prompt'),
            send: document.getElementById('send'),
            stop: document.getElementById('stop'),
        };

        let busy = false;
        // {id, type} of the agent named in the last `init`, or null.
        let currentAgent = null;
        // Assistant message of the running turn: {node, body, buffer, frame, rendered}.
        let reply = null;
        let stickToBottom = true;

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
            el.agentName.textContent = strings.noAgent;
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
            el.messages.setAttribute('aria-busy', String(value));
            if (!value && document.activeElement === el.stop)
                el.prompt.focus();
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
            if (busy)
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
            if (busy)
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
                reply = {node, body, buffer: '', frame: 0, rendered: ''};
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
            return target;
        }

        function addStatus(node, reason, text) {
            const status = document.createElement('p');
            status.className = 'message__status';
            status.dataset.status = reason;
            status.textContent = text;
            node.append(status);
        }

        // --- dispatch handlers ----------------------------------------------------------

        function onInit(event) {
            applyTheme(event.theme);
            applyFontSize(event.font_size);
            const agents = Array.isArray(event.agents) ? event.agents : [];
            if (agents.length === 0) {
                currentAgent = null;
                el.agentName.textContent = strings.noAgent;
                showScreen('empty');
                return;
            }
            const current = agents.find(agent => agent?.id === event.current) ?? agents[0];
            currentAgent = {
                id: typeof current?.id === 'string' ? current.id : null,
                type: typeof current?.type === 'string' ? current.type : null,
            };
            const name = typeof current?.name === 'string' && current.name !== ''
                ? current.name : String(current?.id ?? strings.noAgent);
            el.agentName.textContent = name;
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
            target.buffer += event.text;
            scheduleRender(target);
        }

        function onDone(event) {
            if (!busy && !reply)
                return;
            const reason = typeof event.stop_reason === 'string' ? event.stop_reason : 'end_turn';
            let target = finishReply();
            const marker = Object.hasOwn(strings.stopReasons, reason)
                ? strings.stopReasons[reason] : null;
            if (marker) {
                target ??= {node: appendMessage('assistant').node};
                addStatus(target.node, reason, marker);
            }
            setBusy(false);
            followBottom();
        }

        function onError(event) {
            finishReply();
            const kind = typeof event.kind === 'string' && ERROR_KIND.test(event.kind)
                ? event.kind : 'unknown';
            const {node, body} = appendMessage('error');
            node.dataset.kind = kind;
            node.setAttribute('role', 'alert');
            const title = document.createElement('strong');
            title.className = 'message__title';
            title.textContent = strings.errorTitle;
            const text = document.createElement('p');
            text.className = 'message__text';
            text.textContent = typeof event.message === 'string' && event.message !== ''
                ? event.message : strings.errorTitle;
            body.append(title, text);
            setBusy(false);
            followBottom();
        }

        // A new (empty) conversation: clears the list. Messages of a stored conversation
        // are shown when the history arrives (later stage); for now only the reset.
        function onConversation() {
            const target = reply;
            reply = null;
            if (target?.frame)
                cancelAnimationFrame(target.frame);
            el.messages.replaceChildren();
            setBusy(false);
            stickToBottom = true;
        }

        // --- debug dump (PLAN §12.1) -----------------------------------------------------

        function messageText(node) {
            const copy = node.cloneNode(true);
            for (const bar of copy.querySelectorAll('.code-block__bar'))
                bar.remove();
            return copy.textContent;
        }

        function collectState() {
            const messages = [...el.messages.querySelectorAll(':scope > .message')].map(node => ({
                role: node.dataset.role ?? null,
                text: messageText(node),
                html: node.querySelector('.message__body')?.innerHTML ?? '',
                thinking: '',
                tools: [],
                ...(node.dataset.kind ? {kind: node.dataset.kind} : {}),
            }));
            return {
                screen: currentScreen(),
                agent: currentAgent?.id ?? null,
                badge: Object.hasOwn(BADGES, currentAgent?.type ?? '')
                    ? BADGES[currentAgent.type] : null,
                messages,
                permission_dialog: {open: false, title: ''},
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
            done: onDone,
            error: onError,
        };

        function dispatch(event) {
            if (event === null || typeof event !== 'object' || typeof event.type !== 'string')
                return false;
            const handler = Object.hasOwn(handlers, event.type) ? handlers[event.type] : null;
            if (!handler)
                return false; // Events of later stages (tool_call, …) are ignored for now.
            handler(event);
            return true;
        }

        return Object.freeze({dispatch});
    }

    window.aiPanelChat = Object.freeze({create});
})();
