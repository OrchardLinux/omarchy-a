import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import struct
import tempfile
import unittest
from unittest.mock import patch

STAGE = Path(__file__).resolve().parents[1] / 'desktop/stage.py'
spec = importlib.util.spec_from_file_location('desktop_stage', STAGE)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class GreeterStagingTests(unittest.TestCase):
    def test_trusted_ui_fallback_theme_and_tmpfiles_are_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / 'upstream'
            theme = upstream / 'themes/osaka-jade'
            (theme / 'backgrounds').mkdir(parents=True)
            (theme / 'colors.toml').write_text('foreground = "#ffffff"\n')
            (theme / 'backgrounds/first.webp').write_bytes(b'fallback')
            (upstream / 'applications').mkdir()
            (upstream / 'applications/foot.desktop').write_text('[Desktop Entry]\n')
            outside = root / 'outside-theme'
            outside.mkdir(mode=0o711)
            outside.chmod(0o711)
            (upstream / 'themes/external-theme').symlink_to(outside, target_is_directory=True)
            keyboard = root / 'keyboard'
            elf = bytearray(64)
            elf[:7] = b'\x7fELF\x02\x01\x01'
            struct.pack_into('<HHI', elf, 16, 3, 183, 1)
            struct.pack_into('<H', elf, 52, 64)
            keyboard.write_bytes(elf)
            xpi = root / 'extension.xpi'
            xpi.write_bytes(b'extension')
            target = root / 'payload'
            args = ['stage.py', str(target), '--upstream', str(upstream), '--keyboard', str(keyboard),
                    '--keyboard-sha256', hashlib.sha256(keyboard.read_bytes()).hexdigest(),
                    '--omafox-xpi', str(xpi)]
            with patch.object(sys, 'argv', args), patch.object(stage, 'XPI_SHA', hashlib.sha256(xpi.read_bytes()).hexdigest()):
                previous = os.umask(0o077)
                try:
                    stage.main()
                finally:
                    os.umask(previous)
            for directory in [target, *target.rglob('*')]:
                if not directory.is_symlink() and directory.is_dir():
                    expected = 0o700 if directory.is_relative_to(target / 'home/tablet') else 0o755
                    self.assertEqual(directory.stat().st_mode & 0o777, expected, directory)
            self.assertEqual(outside.stat().st_mode & 0o777, 0o711)
            self.assertTrue((target / 'home/tablet/.local/share/omarchy-ipad/themes/external-theme').is_symlink())
            self.assertEqual((target / 'etc/greetd/config.toml').stat().st_mode & 0o777,
                             (stage.HERE / 'greeter/greetd.toml').stat().st_mode & 0o777)
            self.assertEqual((target / 'usr/local/libexec/arch-ipad-login-session').stat().st_mode & 0o777, 0o755)
            menu = target / 'home/tablet/.local/share/omarchy-ipad/default/omarchy/omarchy-menu.jsonc'
            self.assertIn('"system.shutdown": {"icon":"󰐥","label":"Shutdown","action":"omarchy-system shutdown"}', menu.read_text())
            self.assertIn('"system.reboot": {"icon":"󰜉","label":"Reboot (leaves Linux)","action":"omarchy-system reboot"}', menu.read_text())
            self.assertIn('"label":"Logout","action":"omarchy-system logout"}', menu.read_text())
            for command in ('omarchy-system', 'omarchy-system-lock', 'omarchy-system-wake'):
                self.assertTrue((target / 'usr/local/bin' / command).is_symlink(), command)
            greeter = target / 'usr/share/omarchy-greeter'
            self.assertEqual((greeter / 'plugins/lock/LockView.qml').read_bytes(),
                             (stage.PORT / 'shell/plugins/lock/LockView.qml').read_bytes())
            self.assertTrue((greeter / 'Commons/Color.qml').is_file())
            jade = stage.HERE / 'themes/jade-horse'
            self.assertEqual((greeter / 'default-theme/background').read_bytes(),
                             (jade / 'backgrounds/01-mountain-horses.webp').read_bytes())
            self.assertEqual((greeter / 'default-theme/colors.toml').read_bytes(),
                             (jade / 'colors.toml').read_bytes())
            themes = target / 'home/tablet/.local/share/omarchy-ipad/themes'
            self.assertFalse((themes / 'osaka-jade').exists())
            self.assertEqual((themes / 'jade-horse/icons.theme').read_text().strip(), 'Yaru-sage')
            first_theme = (target / 'usr/local/libexec/arch-ipad-first-theme').read_text()
            self.assertIn('themes/jade-horse', first_theme)
            self.assertIn("'jade-horse' >", first_theme)
            self.assertNotIn('tokyo-night', first_theme)
            self.assertIn('tablet tablet', (target / 'usr/lib/tmpfiles.d/omarchy-greeter-theme.conf').read_text())
            self.assertTrue((target / 'home/tablet/.local/share/omarchy-ipad/bin/omarchy-greeter-theme-publish').is_file())
            # Boot login is the PIN greeter on VT1, not a tty1 autologin.
            greetd = (target / 'etc/greetd/config.toml').read_text()
            self.assertIn('vt = 1', greetd)
            self.assertIn('command = "/usr/local/libexec/omarchy-greeter-session"', greetd)
            self.assertTrue((target / 'etc/systemd/system/greetd.service.d/seatd.conf').is_file())
            self.assertFalse((target / 'etc/systemd/system/getty@tty1.service.d').exists())
            self.assertFalse((target / 'home/tablet/.bash_profile').exists())
            self.assertTrue((target / 'usr/local/libexec/arch-ipad-rotate-output').stat().st_mode & 0o111)
            self.assertTrue((target / 'usr/local/libexec/arch-ipad-touch-output').stat().st_mode & 0o111)


if __name__ == '__main__':
    unittest.main()
