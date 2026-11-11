import js from '@eslint/js';
import globals from 'globals';

// Globals provided by GJS (gnome-shell extensions, tests/gjs). Kept explicit because
// the `globals` package has no GJS preset.
const gjsGlobals = {
    ARGV: 'readonly',
    imports: 'readonly',
    print: 'readonly',
    printerr: 'readonly',
    log: 'readonly',
    logError: 'readonly',
    console: 'readonly',
    global: 'readonly',
    TextEncoder: 'readonly',
    TextDecoder: 'readonly',
    setTimeout: 'readonly',
    clearTimeout: 'readonly',
    setInterval: 'readonly',
    clearInterval: 'readonly',
};

export default [
    {
        ignores: ['app/ui/vendor/**', 'node_modules/**', '.venv/**', 'dist/**', '.run/**',
            'test-results/**', 'playwright-report/**'],
    },
    js.configs.recommended,
    {
        languageOptions: {ecmaVersion: 'latest', sourceType: 'module'},
        rules: {
            'no-unused-vars': ['error', {argsIgnorePattern: '^_', varsIgnorePattern: '^_'}],
        },
    },
    {
        files: ['app/ui/**/*.js'],
        languageOptions: {globals: {...globals.browser}},
    },
    {
        files: ['extension/**/*.js', 'tests/gjs/**/*.js'],
        languageOptions: {globals: gjsGlobals},
    },
    {
        files: ['tests/ui/**/*.{js,mjs}', '*.mjs', 'scripts/**/*.mjs'],
        languageOptions: {globals: {...globals.node, ...globals.browser}},
    },
];
