// Chat UI entry point. Talks to Python only through the `bridge` script message handler
// (PLAN §12.2). Loaded as a classic deferred script: module scripts are blocked on file://
// in Chromium, which is the Playwright fallback browser.
'use strict';

(function () {
    function post(message) {
        const handler = window.webkit?.messageHandlers?.bridge;
        if (handler) {
            handler.postMessage(message);
        }
    }

    // `defer` runs this after the document is parsed, so the DOM is ready here.
    post({type: 'ready'});
})();
