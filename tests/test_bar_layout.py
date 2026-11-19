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
        self.assertEqual(ids['left'], ['omarchy.menu', 'omarchy.indicators', 'omarchy.network'])
        self.assertEqual(ids['center'], ['omarchy.clock'])
        self.assertEqual(ids['right'], ['omarchy.power', 'omarchy.overflow'])
        # Touch slots are 40 px, the battery with its percentage two of them, and
        # beside a centered clock a 375 px bar has room for three a side.
        slots = lambda section: sum(2 if name == 'omarchy.power' else 1 for name in ids[section])
        self.assertLessEqual(slots('left'), 3)
        self.assertLessEqual(slots('right'), 3)

    @unittest.skipUnless(shutil.which('node'), 'node is required for bar model validation')
    def test_a_narrow_bar_drops_no_widget(self):
        # What does not fit beside the clock is one press of the overflow widget
        # away, and the press after the last page is the first page again.
        pages = json.loads(self.node(r"""
const model = require(process.argv[1]);
const layout = JSON.parse(require('node:fs').readFileSync(process.argv[2], 'utf8')).bar.layout;
const ids = page => Object.fromEntries(Object.entries(model.narrowLayout(layout, page))
  .map(([section, entries]) => [section, entries.map(entry => entry.id)]));
const count = model.narrowPages(layout);
console.log(JSON.stringify({count, pages: [...Array(count + 1).keys()].map(ids),
  monitor: model.narrowPageOf(layout, 'omarchy.monitor'), power: model.narrowPageOf(layout, 'omarchy.power'),
  none: model.narrowPageOf(layout, 'omarchy.absent'),
  plain: model.narrowLayout({left: [{id: 'a'}], right: [{id: 'b'}]}).right.map(entry => entry.id)}));
""", BAR / 'BarModel.js', CONFIG))
        configured = [entry['id'] for entries in json.loads(CONFIG.read_text())['bar']['layout'].values()
                      for entry in entries]
        shown = {name for page in pages['pages'] for entries in page.values() for name in entries}
        self.assertEqual(shown - {'omarchy.overflow'}, set(configured))
        self.assertEqual(pages['count'], 2)
        second = pages['pages'][1]
        self.assertEqual(second['left'], ['omarchy.menu', 'omarchy.audio', 'omarchy.bluetooth'])
        self.assertEqual(second['center'], ['omarchy.clock'])
        self.assertEqual(second['right'], ['omarchy.monitor', 'ipadlinux.controlcenter', 'omarchy.overflow'])
        # Three 40 px touch slots a side, as on the first page.
        self.assertTrue(all(len(page[side]) <= 3 for page in pages['pages'] for side in ('left', 'right')))
        self.assertEqual(pages['pages'][2], pages['pages'][0])
        self.assertEqual((pages['monitor'], pages['power'], pages['none']), (1, 0, -1))
        # A layout with nothing taken off has no overflow widget.
        self.assertEqual(pages['plain'], ['b'])
        manifest = json.loads((BAR / 'widgets/Overflow.manifest.json').read_text())
        self.assertEqual(manifest['id'], 'omarchy.overflow')
        self.assertTrue((BAR / 'widgets' / manifest['entryPoints']['barWidget']).is_file())

    def test_the_bar_layout_is_the_narrow_bars_source(self):
        bar = (BAR / 'Bar.qml').read_text()
        self.assertIn('layoutConfig = narrow ? BarModel.narrowLayout(configuredLayout, overflowPage) : configuredLayout', bar)


if __name__ == '__main__':
    unittest.main()
