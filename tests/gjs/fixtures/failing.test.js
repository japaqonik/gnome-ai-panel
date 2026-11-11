// Fixture for sanity.test.js: one passing and one failing test.
// Not picked up by the default run (lives in a subdirectory).
import {test, assertEqual} from '../harness.js';

test('fixture passes', () => assertEqual(1, 1));
test('fixture fails on purpose', () => assertEqual(1, 2));
