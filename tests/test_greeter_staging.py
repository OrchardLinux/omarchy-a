import hashlib
import importlib.util
from pathlib import Path
import sys
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
            keyboard = root / 'keyboard'
            keyboard.write_bytes(b'keyboard')
            xpi = root / 'extension.xpi'
            xpi.write_bytes(b'extension')
            daemon = root / 'apple-aop-daemon'
            daemon.write_bytes(b'AArch64 test fixture')
            target = root / 'payload'
            args = ['stage.py', str(target), '--upstream', str(upstream), '--keyboard', str(keyboard),
                    '--keyboard-sha256', hashlib.sha256(keyboard.read_bytes()).hexdigest(),
                    '--omafox-xpi', str(xpi), '--aop-daemon', str(daemon)]
            with patch.object(sys, 'argv', args), patch.object(stage, 'XPI_SHA', hashlib.sha256(xpi.read_bytes()).hexdigest()):
                stage.main()
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
            self.assertEqual((target / 'usr/libexec/apple-aop-daemon').read_bytes(), daemon.read_bytes())
            self.assertTrue((target / 'usr/libexec/apple-aop').stat().st_mode & 0o111)
            self.assertTrue((target / 'usr/lib/systemd/user/apple-aop-rotate.service').is_file())


if __name__ == '__main__':
    unittest.main()
