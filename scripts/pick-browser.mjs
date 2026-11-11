// Prints the Playwright browser for `make test-ui` (PLAN §7: PW_BROWSER=chromium is the fallback).
// - PW_BROWSER set: printed as is, no probing (an explicit choice must fail loudly).
// - otherwise: tries to launch WebKit; prints "webkit" when it starts, else prints "chromium"
//   and explains on stderr which host libraries are missing.
import {webkit} from '@playwright/test';

const explicit = process.env.PW_BROWSER;
if (explicit) {
    console.log(explicit);
    process.exit(0);
}

try {
    const browser = await webkit.launch({timeout: 30000});
    await browser.close();
    console.log('webkit');
} catch (error) {
    const firstLines = String(error?.message ?? error).split('\n').slice(0, 12).join('\n');
    console.error('test-ui: Playwright WebKit cannot launch on this machine, falling back to chromium.');
    console.error('test-ui: install its host libraries once with: sudo npx playwright install-deps webkit');
    console.error(firstLines);
    console.log('chromium');
}
