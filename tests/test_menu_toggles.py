import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
BIN = PROJECT / 'desktop/shell/bin'


class MenuToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.rc = self.home / '.config/labwc/rc.xml'
        self.rc.parent.mkdir(parents=True)
        shutil.copy(PROJECT / 'desktop/shell/labwc-rc.xml', self.rc)
        self.env = {**os.environ, 'HOME': str(self.home)}
        self.env.pop('XDG_CONFIG_HOME', None)

    def run_bin(self, name, *args, **env):
        return subprocess.run(['bash', str(BIN / name), *args], env={**self.env, **env},
                              capture_output=True, text=True)

    def test_toggle_enabled_reflects_the_flag(self):
        self.assertEqual(self.run_bin('omarchy-toggle-enabled', 'bar-off').returncode, 1)
        flag = self.home / '.local/state/omarchy/toggles/bar-off'
        flag.parent.mkdir(parents=True)
        flag.touch()
        self.assertEqual(self.run_bin('omarchy-toggle-enabled', 'bar-off').returncode, 0)
        self.assertEqual(self.run_bin('omarchy-toggle-enabled', '../x').returncode, 2)

    def test_maximize_windows_round_trip_reloads_labwc(self):
        original = self.rc.read_text()
        flag = self.home / '.local/state/omarchy/toggles/maximize-windows'
        for expect_on in (True, False):
            # Stand-in for labwc: SIGHUP ends a sleep, proving the reload signal.
            labwc = subprocess.Popen(['sleep', '30'])
            self.addCleanup(labwc.kill)
            result = self.run_bin('omarchy-toggle-maximize-windows', LABWC_PID=str(labwc.pid))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(labwc.wait(5), -1)  # SIGHUP
            self.assertEqual(flag.exists(), expect_on)
            tree = ET.fromstring(self.rc.read_bytes())
            rules = tree.findall("./windowRules/windowRule[@identifier='*']/action[@name='Maximize']")
            self.assertEqual(len(rules), 1 if expect_on else 0)
        self.assertEqual(self.rc.read_text(), original)

    def test_menu_toggles_use_shipped_commands(self):
        menu = (PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc').read_text()
        for key in ('maximize-windows-on', 'maximize-windows-off'):
            self.assertIn('"trigger.toggle.%s"' % key, menu)
        for command in ('omarchy-toggle-maximize-windows', 'omarchy-toggle-bar', 'omarchy-toggle-enabled'):
            self.assertIn(command, menu)
            self.assertTrue((BIN / command).is_file(), command)
        bar = re.search(r'"appearance\.top-bar\.show": \{[^}]*\}', menu).group(0)
        self.assertIn('omarchy-toggle-enabled bar-off', bar)
