from pathlib import Path
import shutil
import subprocess
import unittest

MODEL = Path(__file__).resolve().parents[1] / 'desktop/shell/shell/Commons/TimeFormatModel.js'


@unittest.skipUnless(shutil.which('node'), 'node is required for the time format')
class TimeFormatTests(unittest.TestCase):
    # Settings > Date & Time's 24-Hour Time flips the bar clock's format, and
    # every clock reads 12 or 24 hours from it.
    def test_the_switch_flips_hours_and_keeps_the_style(self):
        script = r'''
const assert = require('assert');
const T = require(process.argv[1]);
// Every format upstream's Appearance > Clock offers, both ways.
const pairs = [['dddd HH:mm', 'dddd h:mm AP'], ['dddd HH:mm:ss', 'dddd h:mm:ss AP'], ['HH:mm', 'h:mm AP'],
               ['ddd d MMM HH:mm', 'ddd d MMM h:mm AP'], ['yyyy-MM-dd HH:mm', 'yyyy-MM-dd h:mm AP']];
for (const [h24, h12] of pairs) {
  assert.equal(T.is24(h24), true, h24); assert.equal(T.is24(h12), false, h12);
  assert.equal(T.flipped(h24, false), h12); assert.equal(T.flipped(h12, true), h24);
}
// No hours at all (the week format) reads as 24-hour and stays as it is.
assert.equal(T.is24("d MMMM 'W'ww yyyy"), true);
assert.equal(T.flipped("d MMMM 'W'ww yyyy", false), "d MMMM 'W'ww yyyy");
// The clock's format from the shell's config; HH:mm without one.
assert.equal(T.clockFormat(JSON.stringify({ bar: { layout: { center: [{ id: 'omarchy.clock', format: 'h:mm AP' }] } } })), 'h:mm AP');
assert.equal(T.clockFormat(''), 'HH:mm');
assert.equal(T.clockFormat('{broken'), 'HH:mm');
'''
        result = subprocess.run(['node', '-e', script, str(MODEL)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
