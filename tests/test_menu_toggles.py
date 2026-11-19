import os
from pathlib import Path
import re
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
        self.env = {**os.environ, 'HOME': str(self.home)}

    def run_bin(self, name, *args, **env):
        return subprocess.run(['bash', str(BIN / name), *args], env={**self.env, **env},
                              capture_output=True, text=True)

    def toggle_enabled(self, *args):
        return self.run_bin('omarchy-toggle-enabled', *args).returncode

    def test_toggle_enabled_reflects_the_flag(self):
        self.assertEqual(self.toggle_enabled('bar-off'), 1)
        flag = self.home / '.local/state/omarchy/toggles/bar-off'
        flag.parent.mkdir(parents=True)
        flag.touch()
        self.assertEqual(self.toggle_enabled('bar-off'), 0)
        self.assertEqual(self.toggle_enabled('../x'), 2)

    def assert_maximizes(self, rules):
        tree = ET.fromstring(rules.read_bytes())
        found = tree.findall("./windowRules/windowRule[@identifier='*']/action[@name='Maximize']")
        self.assertEqual(len(found), 1)
        # About and Omacalc keep the size that fits what they show; their rules come after the one for all.
        identifiers = [rule.get('identifier') for rule in tree.findall('./windowRules/windowRule')]
        self.assertEqual(identifiers, ['*', 'org.omarchy.about', 'omacalc'])
        for app in identifiers[1:]:
            kept = tree.findall("./windowRules/windowRule[@identifier='%s']/action[@name='UnMaximize']" % app)
            self.assertEqual(len(kept), 1, app)

    def test_maximize_windows_is_on_until_turned_off(self):
        off = self.home / '.local/state/omarchy/toggles/maximize-windows-off'
        rules = self.home / '.local/state/omarchy/xdg-config/labwc/rc.xml'
        # Login writes the rule for a person who never chose.
        result = self.run_bin('omarchy-toggle-maximize-windows', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_maximizes(rules)
        for expect_on in (False, True):
            # Stand-in for labwc: SIGHUP ends a sleep, proving the reload signal.
            labwc = subprocess.Popen(['sleep', '30'])
            self.addCleanup(labwc.kill)
            result = self.run_bin('omarchy-toggle-maximize-windows', LABWC_PID=str(labwc.pid))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(labwc.wait(5), -1)  # SIGHUP
            self.assertEqual(off.exists(), not expect_on)
            self.assertEqual(self.toggle_enabled('maximize-windows-off'), 1 if expect_on else 0)
            self.assertEqual(rules.exists(), expect_on)
            if expect_on:
                self.assert_maximizes(rules)
        # Turned off, a login keeps it off.
        self.run_bin('omarchy-toggle-maximize-windows')
        self.run_bin('omarchy-toggle-maximize-windows', '--apply')
        self.assertFalse(rules.exists())
        self.assertFalse((self.home / '.config').exists())

    def test_the_on_flag_from_before_the_default_goes(self):
        legacy = self.home / '.local/state/omarchy/toggles/maximize-windows'
        legacy.parent.mkdir(parents=True)
        legacy.touch()
        self.run_bin('omarchy-toggle-maximize-windows', '--apply')
        self.assertFalse(legacy.exists())

    def test_login_writes_the_maximize_rule_before_labwc_starts(self):
        session = (PROJECT / 'desktop/configuration/login-session').read_text()
        self.assertLess(session.index('omarchy-toggle-maximize-windows --apply'), session.index('/usr/bin/labwc -m'))

    def test_session_merges_the_toggle_config_into_labwc(self):
        # Releases replace ~/.config/labwc/rc.xml, so toggle rules must come from the
        # state directory via labwc's XDG merge, never from edits to rc.xml.
        session = (PROJECT / 'desktop/configuration/login-session').read_text()
        self.assertIn('export XDG_CONFIG_DIRS="$HOME/.local/state/omarchy/xdg-config:', session)
        # Labwc is the last thing the login starts, again after each logout.
        loop = session[session.index('\nwhile :; do\n'):]
        self.assertIn('  /usr/bin/labwc -m || true\n', loop)
        self.assertEqual(session.rstrip().splitlines()[-1], 'done')
        toggle = (BIN / 'omarchy-toggle-maximize-windows').read_text()
        self.assertIn('$HOME/.local/state/omarchy/xdg-config/labwc/rc.xml', toggle)
        code = [line for line in toggle.splitlines() if not line.lstrip().startswith('#')]
        self.assertFalse([line for line in code if '.config/labwc' in line])

    def test_menu_toggles_use_shipped_commands(self):
        menu = (PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc').read_text()
        for key in ('maximize-windows-on', 'maximize-windows-off'):
            self.assertIn('"trigger.toggle.%s"' % key, menu)
        for command in ('omarchy-toggle-maximize-windows', 'omarchy-toggle-bar', 'omarchy-toggle-enabled'):
            self.assertIn(command, menu)
            self.assertTrue((BIN / command).is_file(), command)
        bar = re.search(r'"appearance\.top-bar\.show": \{[^}]*\}', menu).group(0)
        self.assertIn('omarchy-toggle-enabled bar-off', bar)
