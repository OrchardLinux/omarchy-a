from pathlib import Path
import os
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-brightness-display'


class BrightnessDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.device = self.base / '20e200080.backlight'
        self.device.mkdir()
        (self.device / 'max_brightness').write_text('2047\n')
        self.set_raw(731)

    def set_raw(self, value):
        (self.device / 'brightness').write_text(f'{value}\n')

    def raw(self):
        return int((self.device / 'brightness').read_text())

    def run_script(self, *args):
        env = {**os.environ, 'IPADLINUX_BACKLIGHT_DIR': str(self.base)}
        env.pop('OMARCHY_TOUCH_MODE', None)
        return subprocess.run(['bash', str(SCRIPT), *args], env=env,
                              capture_output=True, text=True)

    def test_relative_steps(self):
        self.assertEqual(self.run_script('--no-osd', '+5%').stdout, '41\n')
        self.assertEqual(self.raw(), 839)
        self.assertEqual(self.run_script('--no-osd', '-5%').stdout, '36\n')
        self.assertEqual(self.raw(), 737)

    def test_steps_do_not_light_a_panel_turned_off_by_the_toggle(self):
        for step in ('+5%', '-5%'):
            with self.subTest(step=step):
                self.set_raw(0)
                result = self.run_script('--no-osd', step)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '0\n')
                self.assertEqual(self.raw(), 0)

    def test_absolute_value_still_turns_the_panel_on(self):
        self.set_raw(0)
        self.assertEqual(self.run_script('--no-osd', '50%').stdout, '50\n')
        self.assertEqual(self.raw(), 1024)
