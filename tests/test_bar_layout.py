"""The bar's layout, and what a phone's narrow bar makes of it."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

PROJECT = Path(__file__).resolve().parents[1]
BAR = PROJECT / 'desktop/shell/shell/plugins/bar'
CONFIG = PROJECT / 'desktop/shell/config/omarchy/shell.json'


class BarLayoutTests(unittest.TestCase):
    def node(self, script, *args):
        result = subprocess.run(['node', '-e', script, *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    @unittest.skipUnless(shutil.which('node'), 'node is required for bar model validation')
    def test_a_phone_bar_fits_beside_the_clock(self):
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
        self.assertEqual(ids['right'], ['omarchy.power'])
        # Touch slots are 40 px, the battery with its percentage two of them, and
        # beside a centered clock a 375 px bar has room for three a side.
        slots = lambda section: sum(2 if name == 'omarchy.power' else 1 for name in ids[section])
        self.assertLessEqual(slots('left'), 3)
        self.assertLessEqual(slots('right'), 3)

    def test_the_bar_layout_is_the_narrow_bars_source(self):
        bar = (BAR / 'Bar.qml').read_text()
        self.assertIn('layoutConfig = narrow ? BarModel.narrowLayout(configuredLayout) : configuredLayout', bar)


if __name__ == '__main__':
    unittest.main()
