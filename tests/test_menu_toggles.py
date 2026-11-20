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
        # An iPad's panel unless a test says otherwise (the host's own is not asked).
        self.drm = self.home / 'drm'
        self.panel('1536x2048')
        self.env = {**os.environ, 'HOME': str(self.home), 'OMARCHY_DRM_ROOT': str(self.drm)}

    def panel(self, mode):
        modes = self.drm / 'card0-DSI-1/modes'
        modes.parent.mkdir(parents=True, exist_ok=True)
        modes.write_text(mode + '\n')

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

    def assert_maximizes(self, rules, phone=False):
        tree = ET.fromstring(rules.read_bytes())
        found = tree.findall("./windowRules/windowRule[@identifier='*']/action[@name='Maximize']")
        self.assertEqual(len(found), 1)
        # About and Omacalc keep the size that fits what they show; their rules come after the one for all.
        # On a phone every window fills the screen.
        identifiers = [rule.get('identifier') for rule in tree.findall('./windowRules/windowRule')]
        self.assertEqual(identifiers, ['*'] if phone else ['*', 'org.omarchy.about', 'omacalc'])
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

    def test_on_a_phone_about_and_omacalc_fill_the_screen_too(self):
        rules = self.home / '.local/state/omarchy/xdg-config/labwc/rc.xml'
        self.panel('750x1334')   # the iPhone 7: 375 wide at scale 2
        result = self.run_bin('omarchy-toggle-maximize-windows', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_maximizes(rules, phone=True)
        # A phone set to scale 1 is as wide as a small tablet.
        settings = self.home / '.local/state/omarchy/monitors/settings'
        settings.parent.mkdir(parents=True)
        settings.write_text('750x1334\t60\t1\tDSI-1\n')
        self.run_bin('omarchy-toggle-maximize-windows', '--apply')
        self.assert_maximizes(rules)

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
        toggle = (BIN / 'omarchy-labwc-window-rules').read_text()
        self.assertIn('$HOME/.local/state/omarchy/xdg-config/labwc/rc.xml', toggle)
        code = [line for line in toggle.splitlines() if not line.lstrip().startswith('#')]
        self.assertFalse([line for line in code if '.config/labwc' in line])

    def test_title_bars_are_on_until_turned_off(self):
        rules = self.home / '.local/state/omarchy/xdg-config/labwc/rc.xml'
        undecorated = "./theme/maximizedDecoration[.='none']"
        self.run_bin('omarchy-toggle-maximize-windows', '--apply')
        self.assertEqual(ET.fromstring(rules.read_bytes()).findall(undecorated), [])
        labwc = subprocess.Popen(['sleep', '30'])
        try:
            result = self.run_bin('omarchy-toggle-window-titlebars', LABWC_PID=str(labwc.pid))
            self.assertEqual(result.returncode, 0, result.stderr)
            tree = ET.fromstring(rules.read_bytes())
            self.assertEqual(len(tree.findall(undecorated)), 1)
            # Both toggles' rules live in the one file.
            self.assertEqual(len(tree.findall("./windowRules/windowRule[@identifier='*']/action[@name='Maximize']")), 1)
        finally:
            labwc.kill()
            labwc.wait()
        labwc = subprocess.Popen(['sleep', '30'])
        try:
            self.run_bin('omarchy-toggle-window-titlebars', LABWC_PID=str(labwc.pid))
        finally:
            labwc.kill()
            labwc.wait()
        self.assertEqual(ET.fromstring(rules.read_bytes()).findall(undecorated), [])

    def test_menu_toggles_use_shipped_commands(self):
        menu = (PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc').read_text()
        for key in ('maximize-windows-on', 'maximize-windows-off'):
            self.assertIn('"trigger.toggle.%s"' % key, menu)
        for command in ('omarchy-toggle-maximize-windows', 'omarchy-toggle-bar', 'omarchy-toggle-enabled'):
            self.assertIn(command, menu)
            self.assertTrue((BIN / command).is_file(), command)
        bar = re.search(r'"appearance\.top-bar\.show": \{[^}]*\}', menu).group(0)
        self.assertIn('omarchy-toggle-enabled bar-off', bar)
