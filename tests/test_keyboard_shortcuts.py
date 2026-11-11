from collections import Counter
from pathlib import Path
import shlex
import unittest
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]


class KeyboardShortcutTests(unittest.TestCase):
    def setUp(self):
        self.tree = ET.fromstring((PROJECT / 'desktop/shell/labwc-rc.xml').read_bytes())
        self.bindings = self.tree.findall('./keyboard/keybind')

    def action(self, key):
        found = [b for b in self.bindings if b.get('key') == key]
        self.assertEqual(len(found), 1, key)
        return found[0].find('action')

    def test_every_key_is_bound_once(self):
        counts = Counter(b.get('key') for b in self.bindings)
        self.assertEqual([key for key, n in counts.items() if n > 1], [])

    def test_executed_programs_ship_with_the_image(self):
        packages = set((PROJECT / 'system/packages.txt').read_text().split())
        scripts = {p.name for p in (PROJECT / 'desktop/shell/bin').iterdir()}
        for binding in self.bindings:
            action = binding.find('action')
            if action.get('name') != 'Execute':
                continue
            program = shlex.split(action.get('command'))[0]
            if program == 'sh':
                # sh -c 'setup && program …': the program is the last command.
                program = shlex.split(shlex.split(action.get('command'))[2].split('&&')[-1])[0]
            if program.startswith('/'):
                continue
            self.assertTrue(program in packages or program in scripts, (binding.get('key'), program))

    def test_omarchy_style_shortcuts(self):
        self.assertEqual(self.action('W-Return').get('command'), 'uwsm-app -- foot')
        self.assertEqual(self.action('W-S-b').get('command'), 'uwsm-app -- firefox')
        self.assertEqual(self.action('W-S-t').get('command'), 'omarchy-launch-or-focus omactivity')
        self.assertEqual(self.action('W-space').get('command'), 'omarchy-shell omarchy.dock apps')
        self.assertIn('"menu":"root"', self.action('W-A-space').get('command'))
        self.assertIn('"menu":"system"', self.action('W-Escape').get('command'))
        self.assertEqual(self.action('W-w').get('name'), 'Close')
        for key, direction in (('Up', 'up'), ('Down', 'down'), ('Left', 'left'), ('Right', 'right')):
            self.assertEqual(self.action('W-S-' + key).get('direction'), direction)
            self.assertTrue(self.action('W-' + key).get('name').endswith('WindowImmediate'))

    def test_overview_triggers(self):
        # Super+Tab, four fingers and Home pressed twice open the same overview.
        self.assertEqual(self.action('W-Tab').get('name'), 'ToggleOverview')
        overview = self.tree.find('./overview')
        self.assertEqual(overview.get('swipe'), 'yes')
        scripts = {p.name for p in (PROJECT / 'desktop/shell/bin').iterdir()}
        for attribute in ('openCommand', 'closeCommand', 'emptyCommand'):
            self.assertIn(shlex.split(overview.get(attribute))[0], scripts)
        # Neither command may toggle: both run without knowing the drawer's state.
        shell = (PROJECT / 'desktop/shell/shell/shell.qml').read_text()
        self.assertIn('function openApps()', shell)
        self.assertIn('function closeApps()', shell)
        self.assertIn('omarchy.dock openApps', overview.get('emptyCommand'))
        changed = (PROJECT / 'desktop/shell/bin/omarchy-overview-changed').read_text()
        self.assertIn('omarchy.dock closeApps', changed)
        self.assertIn('omarchy-keyboard hide', changed)
        self.assertIn('mode == "hide"', (PROJECT / 'desktop/shell/bin/omarchy-keyboard').read_text())
        home = (PROJECT / 'desktop/shell/bin/omarchy-home-button').read_text()
        self.assertIn('labwc --overview', home)
        # One press waits for a second before the drawer opens: two presses
        # must not flash the drawer on the way to the overview.
        self.assertLess(home.index('sleep'), home.index('omarchy-shell omarchy.dock apps'))
        # Home closes the overview from the script, not inside labwc: a Home
        # that is half of Home + Power must leave the overview on screen.
        self.assertLess(home.index('combo'), home.index('omarchy-overview-open'))
        # A press that woke the screen in the grace before the lock opens nothing.
        self.assertLess(home.index('== wake'), home.index('omarchy-overview-open'))
        self.assertIn('omarchy-overview-open"', changed)
        self.assertIn('omarchy-overview-open', (PROJECT / 'desktop/configuration/labwc-autostart').read_text())
        patch = (PROJECT / 'desktop/labwc/0004-overview.patch').read_text()
        self.assertNotIn('XKB_KEY_XF86HomePage', patch)
        # The greeter has nothing to switch between.
        self.assertNotIn('overview', (PROJECT / 'desktop/greeter/labwc/rc.xml').read_text())

    def test_super_tap_release_bindings_are_unchanged(self):
        for key in ('Super_L', 'Super_R'):
            binding = [b for b in self.bindings if b.get('key') == key][0]
            self.assertEqual(binding.get('onRelease'), 'yes')
