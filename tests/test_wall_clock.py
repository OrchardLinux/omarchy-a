from pathlib import Path
import shutil
import subprocess
import unittest

MODEL = Path(__file__).resolve().parents[1] / 'desktop/shell/shell/plugins/panels/clock/Model.js'


@unittest.skipUnless(shutil.which('node'), 'node is required for the clock model')
class WallClockTests(unittest.TestCase):
    # The bar clock's minute timer stops while the tablet sleeps; after a wake
    # or a clock change the wall time shows the tick went missing.
    def test_a_wake_or_clock_change_counts_as_a_missed_tick(self):
        script = r'''
const assert = require('assert');
const M = require(process.argv[1]);
const due = 120000;
assert.equal(M.tickMissed(100000, due, 60000), false);         // waiting for the minute
assert.equal(M.tickMissed(120500, due, 60000), false);         // a timer a little late
assert.equal(M.tickMissed(120000 + 7 * 60000, due, 60000), true); // woke seven minutes on
assert.equal(M.tickMissed(60000, due, 60000), false);          // just armed
assert.equal(M.tickMissed(58000, due, 60000), true);           // clock set back
'''
        result = subprocess.run(['node', '-e', script, str(MODEL)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
