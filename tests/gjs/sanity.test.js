import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

import {test, assert} from './harness.js';

const here = GLib.path_get_dirname(GLib.filename_from_uri(import.meta.url)[0]);

function runRunner(fixture) {
    const gjs = GLib.find_program_in_path('gjs');
    assert(gjs, 'gjs not found in PATH');
    const proc = Gio.Subprocess.new(
        [gjs, '-m', GLib.build_filenamev([here, 'run.js']),
            GLib.build_filenamev([here, 'fixtures', fixture])],
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE);
    const [, stdout] = proc.communicate_utf8(null, null);
    return {status: proc.get_exit_status(), stdout};
}

// Kept as a single test so the default run reports exactly "1 passed" (S1-T1 Done when).
test('runner exits non-zero when a test fails or a file fails to load', () => {
    const failing = runRunner('failing.test.js');
    assert(failing.status !== 0, `expected non-zero exit, output:\n${failing.stdout}`);
    assert(failing.stdout.includes('1 passed, 1 failed'), `unexpected summary:\n${failing.stdout}`);

    const broken = runRunner('throws-on-load.test.js');
    assert(broken.status !== 0, `load error must fail the run, output:\n${broken.stdout}`);
    assert(broken.stdout.includes('0 passed, 1 failed'), `unexpected summary:\n${broken.stdout}`);
    assert(broken.stdout.includes('cannot load'), `missing load error:\n${broken.stdout}`);
});
