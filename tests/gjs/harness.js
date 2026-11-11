// Minimal test registry used by tests/gjs/run.js.
// Test files import { test, assert, assertEqual } from './harness.js'.

const registered = [];

export function test(name, fn) {
    registered.push({name, fn});
}

export function takeTests() {
    return registered.splice(0, registered.length);
}

export function assert(condition, message = 'assertion failed') {
    if (!condition)
        throw new Error(message);
}

export function assertEqual(actual, expected, message = '') {
    const a = JSON.stringify(actual);
    const e = JSON.stringify(expected);
    if (a !== e)
        throw new Error(`${message ? `${message}: ` : ''}expected ${e}, got ${a}`);
}
