"""The bar's activity widget: its figures, and that a phone's bar keeps it."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

PROJECT = Path(__file__).resolve().parents[1]
BAR = PROJECT / 'desktop/shell/shell/plugins/bar'
CONFIG = PROJECT / 'desktop/shell/config/omarchy/shell.json'


class ActivityWidgetTests(unittest.TestCase):
    def node(self, script, *args):
        result = subprocess.run(['node', '-e', script, *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    @unittest.skipUnless(shutil.which('node'), 'node is required for bar model validation')
    def test_cpu_and_memory_use_in_percent(self):
        self.node(r'''
const assert = require('node:assert/strict');
const model = require(process.argv[1]);
const before = model.cpuTimes('cpu  100 0 50 800 50 0 0 0 0 0\ncpu0 50 0 25 400 25 0 0 0 0 0\n');
const after = model.cpuTimes('cpu  160 0 90 850 50 0 0 0 0 0\n');
assert.deepEqual(before, {idle: 850, total: 1000});  // waiting for I/O counts as idle
assert.equal(model.cpuPercent(before, after), 67);
assert.equal(model.cpuPercent(null, after), -1);     // one reading says nothing
assert.equal(model.cpuPercent(after, after), -1);
assert.equal(model.cpuTimes('intr 1 2 3'), null);
assert.equal(model.memoryPercent('MemTotal:  1000 kB\nMemFree:  100 kB\nMemAvailable:  250 kB\n'), 75);
assert.equal(model.memoryPercent('MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 50 kB\nCached: 100 kB\n'), 75);
assert.equal(model.memoryPercent(''), -1);
assert.equal(model.label(7, '7', true), '  7%');     // one width whatever the number
assert.equal(model.label(100, '100', true), '100%');
assert.equal(model.label(7, '7', false), '7%');
assert.equal(model.label(-1, '', true), ' --%');
''', BAR / 'widgets/ActivityModel.js')

    @unittest.skipUnless(shutil.which('node'), 'node is required for bar model validation')
    def test_a_phone_bar_keeps_the_widget_and_fits_beside_the_clock(self):
        narrow = json.loads(self.node(r'''
const model = require(process.argv[1]);
const layout = JSON.parse(require('node:fs').readFileSync(process.argv[2], 'utf8')).bar.layout;
const before = JSON.stringify(layout);
const narrow = model.narrowLayout(layout);
if (JSON.stringify(layout) !== before) throw new Error('the configured layout was changed');
console.log(JSON.stringify(narrow));
''', BAR / 'BarModel.js', CONFIG))
        ids = {section: [entry['id'] for entry in entries] for section, entries in narrow.items()}
        self.assertEqual(ids['left'], ['omarchy.menu', 'ipadlinux.keyboard', 'omarchy.network'])
        self.assertEqual(ids['center'], ['omarchy.clock'])
        self.assertEqual(ids['right'], ['omarchy.activity', 'omarchy.power'])
        # Touch slots are 40 px, the battery with its percentage two of them, and
        # beside a centered clock a 375 px bar has room for three a side.
        slots = lambda section: sum(2 if name == 'omarchy.power' else 1 for name in ids[section])
        self.assertLessEqual(slots('left'), 3)
        self.assertLessEqual(slots('right'), 3)

    def test_the_tablet_bar_shows_cpu_use_by_default(self):
        right = json.loads(CONFIG.read_text())['bar']['layout']['right']
        self.assertIn({'id': 'omarchy.activity', 'mode': 'cpu'}, right)
        bar = (BAR / 'Bar.qml').read_text()
        self.assertIn('layoutConfig = narrow ? BarModel.narrowLayout(configuredLayout) : configuredLayout', bar)

    def test_the_widget_starts_no_process_to_read_and_draws_no_shapes(self):
        widget = (BAR / 'widgets/Activity.qml').read_text()
        self.assertNotIn('Process {', widget)
        for banned in ('QtQuick.Shapes', 'ShaderEffect', 'MultiEffect'):
            self.assertNotIn(banned, widget)
        self.assertIn('["uwsm-app", "--", "omactivity", "--tab", root.mode]', widget)


if __name__ == '__main__':
    unittest.main()
