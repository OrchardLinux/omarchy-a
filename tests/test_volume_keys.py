"""The volume keys control the volume, and a new output starts quiet."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-volume'


class VolumeKeys(unittest.TestCase):
    def run_keys(self, action):
        with tempfile.TemporaryDirectory() as directory:
            bin_dir, log = Path(directory), Path(directory) / 'calls'
            (bin_dir / 'omarchy-shell').write_text(f'#!/bin/sh\necho "shell $*" >> {log}\n')
            (bin_dir / 'wpctl').write_text(f'#!/bin/sh\necho "wpctl $*" >> {log}\n'
                                           '[ "$1" = get-volume ] && echo "Volume: 0.45"\nexit 0\n')
            for name in ('omarchy-shell', 'wpctl'):
                (bin_dir / name).chmod(0o755)
            env = {**os.environ, 'PATH': f'{bin_dir}:/usr/bin:/bin'}
            result = subprocess.run(['bash', str(SCRIPT), action], env=env, capture_output=True, text=True)
            return result.returncode, log.read_text().splitlines()

    def test_a_step_then_the_osd_with_the_new_volume(self):
        code, calls = self.run_keys('raise')
        self.assertEqual(code, 0)
        self.assertEqual(calls[0], 'wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+')
        self.assertTrue(calls[-1].startswith('shell -q shell summon omarchy.osd '))
        self.assertIn('"progressText":"45%"', calls[-1])

    def test_mute_toggles(self):
        code, calls = self.run_keys('mute-toggle')
        self.assertEqual(calls[0], 'wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle')

    def test_the_volume_keys_are_bound_to_volume(self):
        rc = (PROJECT / 'desktop/shell/labwc-rc.xml').read_text()
        for key, action in (('XF86AudioRaiseVolume', 'raise'), ('XF86AudioLowerVolume', 'lower')):
            block = rc[rc.index(f'<keybind key="{key}">'):]
            self.assertIn(f'omarchy-volume {action}', block[:block.index('</keybind>')])

    def test_a_new_output_starts_at_ten_percent(self):
        conf = (PROJECT / 'system/overlay/etc/wireplumber/wireplumber.conf.d/60-omarchy-a-volume.conf').read_text()
        self.assertIn('device.routes.default-sink-volume = 0.001', conf)  # 0.1 on the cubic scale

    def test_the_bar_has_the_audio_mixer_and_the_osd_is_on(self):
        config = (PROJECT / 'desktop/shell/config/omarchy/shell.json').read_text()
        self.assertIn('"omarchy.audio"', config)
        self.assertNotIn('"omarchy.osd"', config)  # not in disabledPlugins


if __name__ == '__main__':
    unittest.main()
