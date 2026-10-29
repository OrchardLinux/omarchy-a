import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'desktop/shell/bin/omarchy-theme-set-gnome'


class UpstreamGtkThemeTests(unittest.TestCase):
    def test_light_and_dark_follow_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            bindir = home / 'bin'
            bindir.mkdir()
            log = home / 'settings.log'
            (bindir / 'omarchy-theme-color').write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_MODE"\n')
            (bindir / 'gsettings').write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_LOG"\n')
            for f in bindir.iterdir():
                f.chmod(0o755)
            env = dict(os.environ, HOME=str(home), PATH=f'{bindir}:/usr/bin:/bin',
                       DBUS_SESSION_BUS_ADDRESS='test', TEST_LOG=str(log))
            for mode, gtk, scheme in [('dark', 'Adwaita-dark', 'prefer-dark'),
                                      ('light', 'Adwaita', 'prefer-light')]:
                env['TEST_MODE'] = mode
                subprocess.run(['bash', str(SCRIPT)], env=env, check=True)
                text = log.read_text()
                self.assertIn(f'gtk-theme {gtk}\n', text)
                self.assertIn(f'color-scheme {scheme}\n', text)
                self.assertIn('icon-theme Yaru-blue\n', text)
                log.unlink()

    def test_without_dbus_does_not_modify_settings(self):
        env = dict(os.environ)
        env.pop('DBUS_SESSION_BUS_ADDRESS', None)
        subprocess.run(['bash', str(SCRIPT)], env=env, check=True)


if __name__ == '__main__':
    unittest.main()
