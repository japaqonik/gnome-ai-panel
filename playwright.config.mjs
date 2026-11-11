import {defineConfig, devices} from '@playwright/test';

// PW_BROWSER selects the engine: webkit (default, closest to WebKitGTK) or chromium (fallback).
const browser = process.env.PW_BROWSER || 'webkit';
const deviceFor = {webkit: 'Desktop Safari', chromium: 'Desktop Chrome', firefox: 'Desktop Firefox'};
if (!(browser in deviceFor))
    throw new Error(`PW_BROWSER must be one of ${Object.keys(deviceFor).join(', ')}, got "${browser}"`);

export default defineConfig({
    testDir: 'tests/ui',
    testMatch: '**/*.spec.mjs',
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: 0,
    reporter: 'list',
    use: {trace: 'retain-on-failure'},
    projects: [{name: browser, use: {...devices[deviceFor[browser]], browserName: browser}}],
});
