// Mini test runner for pure extension logic.
// Usage: gjs -m tests/gjs/run.js [file.test.js ...]
// Without arguments it runs every *.test.js next to this file (non-recursive).
// Prints "N passed" (and "M failed") and exits with 1 when anything fails.
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import system from 'system';

import {takeTests} from './harness.js';

const here = GLib.path_get_dirname(GLib.filename_from_uri(import.meta.url)[0]);

function defaultFiles() {
    const dir = Gio.File.new_for_path(here);
    const enumerator = dir.enumerate_children('standard::name,standard::type', Gio.FileQueryInfoFlags.NONE, null);
    const files = [];
    for (let info = enumerator.next_file(null); info; info = enumerator.next_file(null)) {
        if (info.get_file_type() === Gio.FileType.REGULAR && info.get_name().endsWith('.test.js'))
            files.push(GLib.build_filenamev([here, info.get_name()]));
    }
    return files.sort();
}

const files = ARGV.length > 0
    ? ARGV.map(f => Gio.File.new_for_commandline_arg(f).get_path())
    : defaultFiles();

let passed = 0;
let failed = 0;

for (const file of files) {
    try {
        await import(GLib.filename_to_uri(file, null));
    } catch (e) {
        failed++;
        print(`FAIL ${file}: cannot load: ${e}`);
        continue;
    }
    for (const {name, fn} of takeTests()) {
        try {
            await fn();
            passed++;
            print(`ok   ${name}`);
        } catch (e) {
            failed++;
            print(`FAIL ${name}: ${e?.message ?? e}`);
            if (e?.stack)
                print(e.stack);
        }
    }
}

print(failed > 0 ? `${passed} passed, ${failed} failed` : `${passed} passed`);
system.exit(failed > 0 ? 1 : 0);
