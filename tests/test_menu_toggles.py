import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
BIN = PROJECT / 'desktop/shell/bin'


class MenuToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = {**os.environ, 'HOME': str(self.home)}

    def toggle_enabled(self, *args):
        return subprocess.run(['bash', str(BIN / 'omarchy-toggle-enabled'), *args], env=self.env,
                              capture_output=True, text=True).returncode

    def test_toggle_enabled_reflects_the_flag(self):
        self.assertEqual(self.toggle_enabled('bar-off'), 1)
        flag = self.home / '.local/state/omarchy/toggles/bar-off'
        flag.parent.mkdir(parents=True)
        flag.touch()
        self.assertEqual(self.toggle_enabled('bar-off'), 0)
        self.assertEqual(self.toggle_enabled('../x'), 2)

    def test_menu_toggles_use_shipped_commands(self):
        menu = (PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc').read_text()
        for command in ('omarchy-toggle-bar', 'omarchy-toggle-enabled'):
            self.assertIn(command, menu)
            self.assertTrue((BIN / command).is_file(), command)
        bar = re.search(r'"appearance\.top-bar\.show": \{[^}]*\}', menu).group(0)
        self.assertIn('omarchy-toggle-enabled bar-off', bar)
