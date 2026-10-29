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
        packages = set((PROJECT / 'system/j71b/packages.txt').read_text().split())
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
        self.assertEqual(self.action('W-Return').get('command'), 'foot')
        self.assertEqual(self.action('W-S-b').get('command'), 'firefox')
        self.assertEqual(self.action('W-space').get('command'), 'omarchy-shell omarchy.dock apps')
        self.assertIn('"menu":"root"', self.action('W-A-space').get('command'))
        self.assertIn('"menu":"system"', self.action('W-Escape').get('command'))
        self.assertEqual(self.action('W-w').get('name'), 'Close')
        for key, direction in (('Up', 'up'), ('Down', 'down'), ('Left', 'left'), ('Right', 'right')):
            self.assertEqual(self.action('W-S-' + key).get('direction'), direction)
            self.assertTrue(self.action('W-' + key).get('name').endswith('WindowImmediate'))

    def test_super_tap_release_bindings_are_unchanged(self):
        for key in ('Super_L', 'Super_R'):
            binding = [b for b in self.bindings if b.get('key') == key][0]
            self.assertEqual(binding.get('onRelease'), 'yes')
