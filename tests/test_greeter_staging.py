"""The package's layout (desktop/install-tree): the greeter, the Omarchy tree, the user's defaults."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from package_tree import INSTALL, PROJECT, mode, tree

HERE = PROJECT / 'desktop'


@unittest.skipUnless(shutil.which('bash'), 'bash runs desktop/install-tree')
class GreeterStagingTests(unittest.TestCase):
    def test_modes_whatever_the_umask(self):
        target = tree()
        skel = target / 'etc/skel'
        for directory in [target, *target.rglob('*')]:
            if not directory.is_symlink() and directory.is_dir():
                expected = 0o700 if directory.is_relative_to(skel) and directory != skel else 0o755
                self.assertEqual(mode(directory), expected, directory)
        # The package writes into no home: the tablet user's defaults are /etc/skel's.
        self.assertFalse((target / 'home').exists())

    def test_trusted_ui_fallback_theme_and_tmpfiles_are_staged(self):
        target = tree()
        skel = target / 'etc/skel'
        omarchy = target / 'usr/share/omarchy'
        self.assertTrue((omarchy / 'themes/external-theme').is_symlink())
        # greetd owns its config: the package's goes there through its etc-overrides.
        overrides = omarchy / 'etc-overrides'
        self.assertFalse((target / 'etc/greetd').exists())
        self.assertEqual((overrides / 'etc/greetd/config.toml').read_bytes(), (HERE / 'greeter/greetd.toml').read_bytes())
        self.assertEqual((overrides / 'etc/skel/.bashrc').read_bytes(), (HERE / 'configuration/bashrc').read_bytes())
        self.assertEqual(mode(target / 'usr/libexec/arch-ipad-login-session'), 0o755)
        menu = (omarchy / 'default/omarchy/omarchy-menu.jsonc').read_text()
        self.assertIn('"system.shutdown": {"icon":"󰐥","label":"Shutdown","action":"omarchy-system shutdown"}', menu)
        self.assertIn('"system.reboot": {"icon":"󰜉","label":"Reboot (leaves Linux)","action":"omarchy-system reboot"}', menu)
        self.assertIn('"label":"Logout","action":"omarchy-system logout"}', menu)
        # Suspend is offered once the charger PM contract is ready.
        self.assertIn('"when":"command -v ipadlinux-suspend-ready >/dev/null && ipadlinux-suspend-ready"', menu)
        self.assertNotIn('! omarchy-toggle-enabled suspend-off && ! omarchy-sleep-disabled', menu)
        for command in ('omarchy-system', 'omarchy-system-lock', 'omarchy-system-wake', 'omarchy-update',
                        'omarchy-migrate', 'omarchy-launch-floating-terminal-with-presentation'):
            self.assertEqual(os.readlink(target / 'usr/bin' / command), '/usr/share/omarchy/bin/' + command)
            self.assertTrue(mode(omarchy / 'bin' / command) & 0o111, command)
        greeter = target / 'usr/share/omarchy-greeter'
        self.assertEqual((greeter / 'plugins/lock/LockView.qml').read_bytes(),
                         (HERE / 'shell/shell/plugins/lock/LockView.qml').read_bytes())
        self.assertTrue((greeter / 'Commons/Color.qml').is_file())
        # Upstream's Jade Horse is the default theme and the greeter's fallback.
        themes = omarchy / 'themes'
        jade = themes / 'jade-horse'
        self.assertEqual((greeter / 'default-theme/background').read_bytes(),
                         (jade / 'backgrounds/01-mountain-horses.webp').read_bytes())
        self.assertEqual((greeter / 'default-theme/colors.toml').read_bytes(), (jade / 'colors.toml').read_bytes())
        self.assertTrue((themes / 'tokyo-night/colors.toml').is_file())
        # Upstream's app icon sets, drawn in the theme's colors at login and on every switch.
        self.assertTrue((omarchy / 'icons/papercraft/folio.svg.tpl').is_file())
        for name in ('papercraft', 'arcade'):
            self.assertEqual((omarchy / 'icons' / name / 'firefox.svg.tpl').read_bytes(),
                             (HERE / 'icons' / name / 'firefox.svg.tpl').read_bytes())
        self.assertEqual(os.readlink(omarchy / 'icons/papercraft/omactivity.svg.tpl'), 'btop.svg.tpl')
        self.assertIn('omarchy-theme-set-icons', (target / 'usr/libexec/arch-ipad-first-theme').read_text())
        first_theme = (target / 'usr/libexec/arch-ipad-first-theme').read_text()
        self.assertIn('themes/jade-horse', first_theme)
        self.assertIn("'jade-horse' >", first_theme)
        self.assertIn('tablet tablet', (target / 'usr/lib/tmpfiles.d/omarchy-greeter-theme.conf').read_text())
        self.assertTrue((omarchy / 'bin/omarchy-greeter-theme-publish').is_file())
        # Boot login is the PIN greeter on VT1, not a tty1 autologin.
        greetd = (overrides / 'etc/greetd/config.toml').read_text()
        self.assertIn('vt = 1', greetd)
        self.assertIn('command = "/usr/libexec/omarchy-greeter-session"', greetd)
        self.assertTrue(mode(target / 'usr/libexec/omarchy-greeter-session') & 0o111)
        self.assertTrue((target / 'etc/systemd/system/greetd.service.d/seatd.conf').is_file())
        self.assertFalse((target / 'etc/systemd/system/getty@tty1.service.d').exists())
        self.assertFalse((skel / '.bash_profile').exists())
        self.assertTrue(mode(target / 'usr/libexec/arch-ipad-rotate-output') & 0o111)
        self.assertTrue(mode(target / 'usr/libexec/arch-ipad-touch-output') & 0o111)
        # The user's defaults, and the same files where omarchy-refresh-config takes them from.
        for name in ('labwc/rc.xml', 'labwc/autostart', 'foot/foot.ini', 'omarchy-ipad/shell.json'):
            self.assertEqual((skel / '.config' / name).read_bytes(), (omarchy / 'config' / name).read_bytes(), name)
        self.assertIn('. /usr/share/omarchy/default/labwc/autostart', (skel / '.config/labwc/autostart').read_text())
        self.assertTrue(mode(omarchy / 'default/labwc/autostart') & 0o111)
        self.assertTrue((skel / '.local/share/applications/foot.desktop').is_file())
        self.assertTrue((omarchy / 'applications/foot.desktop').is_file())
        # The compiled helpers and the extension.
        self.assertEqual(mode(omarchy / 'trials/wvkbd-mobintl-v0.20-font18-special15-state'), 0o755)
        self.assertEqual(mode(target / 'usr/libexec/omarchy-wtype'), 0o755)
        self.assertTrue((target / 'usr/lib/firefox/distribution/extensions/@omafox.xpi').is_file())
        self.assertFalse(list(target.rglob('__pycache__')))

    def test_missing_inputs_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            result = subprocess.run(['bash', str(INSTALL), str(base / 'root'), str(base), str(base), str(base)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Missing input', result.stderr)
            self.assertFalse((base / 'root').exists())


if __name__ == '__main__':
    unittest.main()
