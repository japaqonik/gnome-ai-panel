// Permission dialog (FR-11, NFR-3). Classic script loaded after strings.js and render.js;
// exposes window.aiPanelPermission.create({post, inert, onClose}) -> {request, closeAll,
// state, isOpen}.
//
// Python dispatches every `permission_request {request_id, tool_call_id, title, kind,
// raw_input, options: [{id, name, kind}]}` as it arrives; they wait in a queue and the
// dialog shows one at a time. A click on an option posts `permission {request_id,
// option_id}`; Esc posts the agent's reject_once option, or option_id null when there is
// none. Nothing is ever chosen automatically. closeAll() (end of the turn, cancel, new
// conversation) drops the dialog and the queue without posting: the backend answers open
// requests of an ended turn itself.
//
// Everything from the agent goes in through textContent.
'use strict';

(function () {
    const strings = window.aiPanelStrings;
    const {formatInput} = window.aiPanelRender;

    const MAX_ID_LENGTH = 256;
    const MAX_KIND_LENGTH = 32;
    // Pointer clicks on the options are ignored this long after a request is shown, so the
    // second click of a double click (or a click aimed at whatever was there before) cannot
    // answer a request the user has not seen yet. Keyboard activation is never delayed.
    const POINTER_GUARD_MS = 400;

    function isId(value) {
        return typeof value === 'string' && value !== '' && value.length <= MAX_ID_LENGTH;
    }

    function shortString(value) {
        return typeof value === 'string' && value !== '' ? value.slice(0, MAX_KIND_LENGTH) : null;
    }

    // Valid options in the agent's order; options with a repeated id are dropped.
    function parseOptions(options) {
        const result = [];
        const ids = new Set();
        for (const option of Array.isArray(options) ? options : []) {
            if (option === null || typeof option !== 'object' || !isId(option.id) ||
                ids.has(option.id))
                continue;
            ids.add(option.id);
            const kind = shortString(option.kind);
            const name = typeof option.name === 'string' && option.name.trim() !== ''
                ? option.name
                : (Object.hasOwn(strings.permissionOptions, kind ?? '')
                    ? strings.permissionOptions[kind] : option.id);
            result.push({id: option.id, name, kind});
        }
        return result;
    }

    function parseRequest(event) {
        if (!isId(event.request_id))
            return null;
        return {
            requestId: event.request_id,
            title: typeof event.title === 'string' && event.title !== ''
                ? event.title : strings.toolUntitled,
            kind: shortString(event.kind),
            input: formatInput(event.raw_input),
            options: parseOptions(event.options),
        };
    }

    function create({post, inert = [], onClose = () => {}}) {
        const el = {
            overlay: document.getElementById('permission-overlay'),
            dialog: document.getElementById('permission-dialog'),
            heading: document.getElementById('permission-heading'),
            title: document.getElementById('permission-title'),
            kind: document.getElementById('permission-kind'),
            inputLabel: document.getElementById('permission-input-label'),
            input: document.getElementById('permission-input'),
            queue: document.getElementById('permission-queue'),
            options: document.getElementById('permission-options'),
        };
        el.heading.textContent = strings.permissionHeading;
        el.inputLabel.textContent = strings.permissionInput;

        // The request shown in the dialog and the ones waiting behind it.
        let current = null;
        let queue = [];
        // Button that receives the focus and the option Esc answers with.
        let rejectButton = null;
        let escapeOption = null;
        // Pending timer that re-enables pointer clicks on the shown request's options.
        let guardTimer = null;

        function known(requestId) {
            return current?.requestId === requestId ||
                queue.some(item => item.requestId === requestId);
        }

        function setBackgroundInert(value) {
            for (const node of inert) {
                if (value)
                    node.setAttribute('inert', '');
                else
                    node.removeAttribute('inert');
            }
        }

        function makeButton(label, kind, optionId) {
            const button = document.createElement('button');
            button.type = 'button';
            const allow = kind?.startsWith('allow_');
            button.className = `button permission__option ${allow
                ? 'button--primary' : 'permission__option--reject'}`;
            button.textContent = label;
            if (optionId !== null)
                button.dataset.optionId = optionId;
            if (kind)
                button.dataset.optionKind = kind;
            button.addEventListener('click', event => {
                // detail: 0 = keyboard or programmatic activation, 1 = single click, >1 =
                // repeated clicks of a double/triple click, never a deliberate answer.
                if (event.detail > 1 || (event.detail > 0 && guardTimer !== null))
                    return;
                answer(optionId);
            });
            return button;
        }

        function renderQueue() {
            el.queue.hidden = queue.length === 0;
            el.queue.textContent = `${strings.permissionQueued}${queue.length}`;
        }

        function show(item) {
            current = item;
            el.title.textContent = item.title;
            el.kind.hidden = item.kind === null;
            el.kind.textContent = item.kind === null ? '' : `${strings.permissionKind} ${
                Object.hasOwn(strings.toolKinds, item.kind) ? strings.toolKinds[item.kind]
                    : item.kind}`;
            el.input.textContent = item.input !== '' ? item.input : strings.permissionNoInput;
            el.input.scrollTop = 0;

            const buttons = item.options.map(o => makeButton(o.name, o.kind, o.id));
            const rejectOnce = item.options.find(o => o.kind === 'reject_once');
            const rejectAny = rejectOnce ?? item.options.find(o => o.kind?.startsWith('reject_'));
            escapeOption = rejectOnce?.id ?? null;
            if (rejectAny) {
                rejectButton = buttons[item.options.indexOf(rejectAny)];
            } else {
                // The agent offers no way to say no: add one (option_id null = rejection).
                rejectButton = makeButton(strings.permissionReject, null, null);
                rejectButton.classList.add('permission__option--fallback');
                buttons.push(rejectButton);
            }
            el.options.replaceChildren(...buttons);
            renderQueue();
            armGuard(buttons);

            const wasHidden = el.overlay.hidden;
            el.overlay.hidden = false;
            if (wasHidden)
                setBackgroundInert(true);
            rejectButton.focus();
        }

        function clearGuard() {
            if (guardTimer !== null) {
                clearTimeout(guardTimer);
                guardTimer = null;
            }
        }

        // aria-disabled (not disabled) keeps the reject button focusable and Enter/Space
        // working while pointer clicks wait.
        function armGuard(buttons) {
            clearGuard();
            for (const button of buttons)
                button.setAttribute('aria-disabled', 'true');
            guardTimer = setTimeout(() => {
                guardTimer = null;
                for (const button of buttons)
                    button.removeAttribute('aria-disabled');
            }, POINTER_GUARD_MS);
        }

        function hide() {
            clearGuard();
            current = null;
            rejectButton = null;
            escapeOption = null;
            el.options.replaceChildren();
            el.overlay.hidden = true;
            setBackgroundInert(false);
            onClose();
        }

        function showNext() {
            const next = queue.shift();
            if (next)
                show(next);
            else
                hide();
        }

        function answer(optionId) {
            if (!current)
                return;
            post({type: 'permission', request_id: current.requestId, option_id: optionId});
            showNext();
        }

        function focusable() {
            return [el.input, ...el.options.querySelectorAll('button')];
        }

        document.addEventListener('keydown', event => {
            if (!current)
                return;
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                answer(escapeOption);
                return;
            }
            if (event.key !== 'Tab')
                return;
            // Keep the focus inside the dialog (aria-modal).
            const items = focusable();
            const index = items.indexOf(document.activeElement);
            const step = event.shiftKey ? -1 : 1;
            event.preventDefault();
            const next = index === -1
                ? (event.shiftKey ? items.length - 1 : 0)
                : (index + step + items.length) % items.length;
            items[next].focus();
        }, true);

        // A click on the backdrop must not leave the focus outside the dialog.
        el.overlay.addEventListener('mousedown', event => {
            if (event.target === el.overlay) {
                event.preventDefault();
                rejectButton?.focus();
            }
        });

        // Returns whether the request was accepted (shown or queued).
        function request(event) {
            const item = parseRequest(event);
            if (!item || known(item.requestId))
                return false;
            if (current) {
                queue.push(item);
                renderQueue();
            } else {
                show(item);
            }
            return true;
        }

        function closeAll() {
            queue = [];
            if (current)
                hide();
        }

        function state() {
            return {open: current !== null, title: current ? el.title.textContent : ''};
        }

        return Object.freeze({request, closeAll, state, isOpen: () => current !== null});
    }

    window.aiPanelPermission = Object.freeze({create});
})();
