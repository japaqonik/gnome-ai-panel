// Markdown rendering of model output (FR-5, FR-6). Classic script loaded after the vendored
// marked, DOMPurify and highlight.js builds; exposes window.aiPanelRender:
//   renderMarkdown(text) -> string     GFM markdown -> sanitised HTML, safe for innerHTML
//   enhanceCodeBlocks(container)       highlights `pre > code` and adds a copy button
/* global marked, DOMPurify, hljs */
'use strict';

(function () {
    const strings = window.aiPanelStrings;
    const COPY_FEEDBACK_MS = 1500;

    // Own instances: settings and hooks do not leak into other users of the globals.
    const parser = new marked.Marked({gfm: true, breaks: false});
    const purifier = DOMPurify(window);

    // Links may only point to web pages, mail addresses or relative targets; everything else
    // (javascript:, data:, vbscript:, file: …) loses its href. Same shape as DOMPurify's
    // default ALLOWED_URI_REGEXP with the scheme list reduced.
    const SAFE_URI = /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i;

    const SANITIZE_CONFIG = Object.freeze({
        USE_PROFILES: {html: true}, // no SVG / MathML
        FORBID_TAGS: ['style', 'script', 'iframe', 'frame', 'frameset', 'object', 'embed',
            'form', 'button', 'select', 'textarea', 'base', 'link', 'meta'],
        FORBID_ATTR: ['style', 'target', 'formaction'],
        ALLOW_DATA_ATTR: false, // data-* is reserved for the UI (e.g. data-external)
        ALLOWED_URI_REGEXP: SAFE_URI,
    });

    purifier.addHook('afterSanitizeAttributes', node => {
        // DOMPurify already drops event handlers; this is a second line of defence.
        for (const name of node.getAttributeNames?.() ?? []) {
            if (name.toLowerCase().startsWith('on'))
                node.removeAttribute(name);
        }
        if (node.tagName === 'A' && node.hasAttribute('href')) {
            // The window opens links in the default browser (S3-T4) based on data-external.
            node.setAttribute('rel', 'noopener noreferrer');
            node.setAttribute('data-external', '');
        }
    });

    function renderMarkdown(text) {
        if (typeof text !== 'string' || text === '')
            return '';
        const html = parser.parse(text, {async: false});
        return purifier.sanitize(html, SANITIZE_CONFIG);
    }

    function languageOf(code) {
        const match = /(?:^|\s)language-(\S+)/.exec(code.className);
        return match ? match[1].toLowerCase() : null;
    }

    function highlight(code) {
        const language = languageOf(code);
        if (language && hljs.getLanguage(language)) {
            // hljs.highlight escapes the source; the result contains only <span class=…>.
            const result = hljs.highlight(code.textContent, {language, ignoreIllegals: true});
            code.innerHTML = result.value;
        }
        code.classList.add('hljs');
        return language;
    }

    function legacyCopy(text) {
        const buffer = document.createElement('textarea');
        buffer.value = text;
        buffer.setAttribute('readonly', '');
        buffer.className = 'clipboard-buffer';
        document.body.append(buffer);
        buffer.select();
        let ok;
        try {
            ok = document.execCommand('copy');
        } catch {
            ok = false;
        }
        buffer.remove();
        return ok;
    }

    async function copyText(text) {
        if (navigator.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch {
                // Permission denied or no clipboard access: try the legacy path.
            }
        }
        return legacyCopy(text);
    }

    const feedbackTimers = new WeakMap();

    function showCopyFeedback(button, text) {
        clearTimeout(feedbackTimers.get(button));
        button.textContent = text;
        button.setAttribute('aria-label', text);
        feedbackTimers.set(button, setTimeout(() => {
            button.textContent = strings.copyCode;
            button.setAttribute('aria-label', strings.copyCodeLabel);
            feedbackTimers.delete(button);
        }, COPY_FEEDBACK_MS));
    }

    function makeCopyButton(code) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'code-block__copy';
        button.textContent = strings.copyCode;
        button.setAttribute('aria-label', strings.copyCodeLabel);
        button.addEventListener('click', async () => {
            // marked ends every code block with a newline that is not part of the code.
            const ok = await copyText(code.textContent.replace(/\n$/, ''));
            showCopyFeedback(button, ok ? strings.copied : strings.copyFailed);
        });
        return button;
    }

    // Idempotent: blocks already enhanced (marked with data-enhanced) are skipped, so it can
    // run after every re-render of a streamed message.
    function enhanceCodeBlocks(container) {
        if (!container || typeof container.querySelectorAll !== 'function')
            return;
        for (const code of container.querySelectorAll('pre > code')) {
            const pre = code.parentElement;
            if (pre.hasAttribute('data-enhanced'))
                continue;
            pre.setAttribute('data-enhanced', '');

            const language = highlight(code);
            const block = document.createElement('div');
            block.className = 'code-block';
            const bar = document.createElement('div');
            bar.className = 'code-block__bar';
            const label = document.createElement('span');
            label.className = 'code-block__lang';
            label.textContent = language ?? '';
            bar.append(label, makeCopyButton(code));
            pre.replaceWith(block);
            block.append(bar, pre);
        }
    }

    // A tool's raw_input as text (tool cards, permission dialog): strings as they are,
    // everything else as indented JSON.
    function formatInput(value) {
        if (value === undefined || value === null)
            return '';
        if (typeof value === 'string')
            return value;
        try {
            return JSON.stringify(value, null, 2) ?? String(value);
        } catch {
            return String(value);
        }
    }

    window.aiPanelRender = Object.freeze({renderMarkdown, enhanceCodeBlocks, formatInput});
})();
