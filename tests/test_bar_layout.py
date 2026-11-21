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
    def test_a_phones_bar_is_logo_and_time_then_status(self):
        narrow = json.loads(self.node(r'''
const model = require(process.argv[1]);
const layout = JSON.parse(require('node:fs').readFileSync(process.argv[2], 'utf8')).bar.layout;
const before = JSON.stringify(layout);
const narrow = model.narrowLayout(layout);
if (JSON.stringify(layout) !== before) throw new Error('the configured layout was changed');
console.log(JSON.stringify({narrow, pages: model.narrowPages(layout)}));
''', BAR / 'BarModel.js', CONFIG))
        ids = {section: [entry['id'] for entry in entries] for section, entries in narrow['narrow'].items()}
        # The logo and the time together on the left, the status on the right
        # (SHELL-SPEC), and no overflow pages.
        self.assertEqual(ids['left'], ['omarchy.menu', 'omarchy.clock'])
        self.assertEqual(ids['center'], [])
        self.assertEqual(ids['right'], ['omarchy.indicators', 'omarchy.audio', 'omarchy.bluetooth', 'omarchy.network',
                                        'omarchy.monitor', 'omarchy.power'])
        self.assertEqual(narrow['pages'], 1)
        # Every icon stays on a phone's bar for now: nothing is hidden there.
        configured = [entry for entries in json.loads(CONFIG.read_text())['bar']['layout'].values() for entry in entries]
        self.assertFalse([entry['id'] for entry in configured if entry.get('narrow') == 'hidden'])

    @unittest.skipUnless(shutil.which('node'), 'node is required for bar model validation')
    def test_a_narrow_bar_drops_no_widget_it_was_not_told_to(self):
        # A widget set to `narrow: false` is one press of the overflow widget
        # away, and the press after the last page is the first page again;
        # only "hidden" leaves a widget out of a narrow bar.
        pages = json.loads(self.node(r"""
const model = require(process.argv[1]);
const layout = {left: [{id: 'menu'}], center: [{id: 'clock'}],
  right: [{id: 'a', narrow: false}, {id: 'b', narrow: false}, {id: 'c', narrow: 'hidden'}, {id: 'power'}]};
const ids = page => Object.fromEntries(Object.entries(model.narrowLayout(layout, page))
  .map(([section, entries]) => [section, entries.map(entry => entry.id)]));
const count = model.narrowPages(layout);
console.log(JSON.stringify({count, pages: [...Array(count + 1).keys()].map(ids),
  a: model.narrowPageOf(layout, 'a'), power: model.narrowPageOf(layout, 'power'),
  none: model.narrowPageOf(layout, 'absent'),
  plain: model.narrowLayout({left: [{id: 'x'}], right: [{id: 'y'}]}).right.map(entry => entry.id)}));
""", BAR / 'BarModel.js'))
        shown = {name for page in pages['pages'] for entries in page.values() for name in entries}
        self.assertEqual(shown - {'omarchy.overflow'}, {'menu', 'clock', 'a', 'b', 'power'})
        self.assertEqual(pages['count'], 2)
        self.assertEqual(pages['pages'][0]['right'], ['power', 'omarchy.overflow'])
        self.assertEqual(pages['pages'][1]['left'], ['menu', 'a', 'b'])
        self.assertEqual(pages['pages'][2], pages['pages'][0])
        self.assertEqual((pages['a'], pages['power'], pages['none']), (1, 0, -1))
        # A layout with nothing taken off has no overflow widget.
        self.assertEqual(pages['plain'], ['y'])
        manifest = json.loads((BAR / 'widgets/Overflow.manifest.json').read_text())
        self.assertEqual(manifest['id'], 'omarchy.overflow')
        self.assertTrue((BAR / 'widgets' / manifest['entryPoints']['barWidget']).is_file())

    def test_the_bar_layout_is_the_narrow_bars_source(self):
        bar = (BAR / 'Bar.qml').read_text()
        self.assertIn('layoutConfig = narrow ? BarModel.narrowLayout(configuredLayout, overflowPage) : configuredLayout', bar)


if __name__ == '__main__':
    unittest.main()
