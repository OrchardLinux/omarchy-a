import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'desktop/shell/bin/omarchy-greeter-theme-publish'
loader = importlib.machinery.SourceFileLoader('greeter_theme_publish', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
publisher = importlib.util.module_from_spec(spec)
loader.exec_module(publisher)


class GreeterThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.state = self.home / '.local/state/omarchy/current'
        self.dest = self.root / 'published'
        self.dest.mkdir()
        (self.state / 'theme').mkdir(parents=True)
        (self.state / 'theme/colors.toml').write_text('foreground = "#ffffff"\n')
        (self.state / 'theme/shell.toml').write_text('[lock]\nbackground = "#123456"\n')
        self.image = self.home / 'wallpaper.png'
        self.image.write_bytes(b'image data')
        (self.state / 'background').symlink_to(self.image)
        self.fallback = self.root / 'fallback'
        self.fallback.write_bytes(b'fallback image')
        for name, value in [('DEST', self.dest), ('STATE', self.state), ('FALLBACK', self.fallback)]:
            p = patch.object(publisher, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(Path, 'home', return_value=self.home)
        p.start()
        self.addCleanup(p.stop)

    def test_publishes_theme_and_selected_image_atomically(self):
        publisher.publish()
        first = (self.dest / 'current').resolve()
        self.assertEqual((first / 'background').read_bytes(), b'image data')
        self.assertIn('#ffffff', (first / 'colors.toml').read_text())
        self.assertIn('#123456', (first / 'shell.toml').read_text())
        self.assertEqual((first / 'background').stat().st_mode & 0o777, 0o644)
        (self.state / 'theme/colors.toml').write_text('foreground = "#000000"\n')
        publisher.publish()
        second = (self.dest / 'current').resolve()
        self.assertNotEqual(first, second)
        self.assertIn('#ffffff', (first / 'colors.toml').read_text())
        self.assertIn('#000000', (second / 'colors.toml').read_text())

    def test_failure_keeps_previous_snapshot(self):
        publisher.publish()
        previous = (self.dest / 'current').resolve()
        (self.state / 'theme/colors.toml').write_bytes(b'x' * (publisher.MAX_CONFIG + 1))
        with self.assertRaises(ValueError):
            publisher.publish()
        self.assertEqual((self.dest / 'current').resolve(), previous)
        self.assertTrue((previous / 'background').exists())

    def test_unknown_background_uses_fallback(self):
        other = self.home / 'unsupported.bin'
        other.write_bytes(b'not an image')
        (self.state / 'background').unlink()
        (self.state / 'background').symlink_to(other)
        publisher.publish()
        self.assertEqual((self.dest / 'current/background').read_bytes(), b'fallback image')

    def test_video_poster_failure_publishes_fallback_and_new_theme(self):
        video = self.home / 'video.mp4'
        video.write_bytes(b'video')
        (self.state / 'background').unlink()
        (self.state / 'background').symlink_to(video)
        with patch.object(publisher.shutil, 'which', return_value='/usr/bin/ffmpegthumbnailer'), \
             patch.object(publisher.subprocess, 'run', side_effect=publisher.subprocess.TimeoutExpired('thumbnail', 8)):
            publisher.publish()
        self.assertEqual((self.dest / 'current/background').read_bytes(), b'fallback image')
        self.assertIn('#ffffff', (self.dest / 'current/colors.toml').read_text())

    def test_user_override_is_in_snapshot(self):
        path = self.home / '.config/omarchy/shell.toml'
        path.parent.mkdir(parents=True)
        path.write_text('[font]\nbase-size = 16\n')
        publisher.publish()
        self.assertEqual((self.dest / 'current/user-shell.toml').read_text(), path.read_text())


if __name__ == '__main__':
    unittest.main()
