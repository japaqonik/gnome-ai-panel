// Stand-in for the WebKitGTK bridge, injected with page.addInitScript before app.js runs.
// Records every postMessage(obj) from the page in window.__bridge.messages and lets tests
// call window.aiPanel.dispatch(obj) through window.__bridge.dispatch (PLAN §12.2).
// Classic browser script: no imports or exports.
'use strict';

(function () {
    const messages = [];
    const bridge = {
        postMessage(message) {
            // WebKitGTK serialises the value; a deep copy keeps the same semantics here.
            messages.push(JSON.parse(JSON.stringify(message)));
        },
    };

    const installed = () => window.webkit?.messageHandlers?.bridge === bridge;

    // Playwright's WebKit may already expose `window.webkit.messageHandlers` (a host object).
    // First try to add `bridge` to it, then fall back to replacing `window.webkit`.
    try {
        Object.defineProperty(window.webkit.messageHandlers, 'bridge', {
            value: bridge,
            configurable: true,
        });
    } catch {
        // No such object, or it is not extensible.
    }
    if (!installed()) {
        Object.defineProperty(window, 'webkit', {
            value: {messageHandlers: {bridge}},
            configurable: true,
        });
    }
    if (!installed())
        throw new Error('mock-bridge: cannot install window.webkit.messageHandlers.bridge');

    window.__bridge = {
        messages,
        dispatch(obj) {
            if (!window.aiPanel || typeof window.aiPanel.dispatch !== 'function')
                throw new Error('window.aiPanel.dispatch is not defined');
            return window.aiPanel.dispatch(obj);
        },
    };
})();
