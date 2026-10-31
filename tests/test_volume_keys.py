"""The volume keys control the volume, and a new output starts quiet."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-volume'


class VolumeKeys(unittest.TestCase):
    def run_keys(self, action, shell_reply):
        with tempfile.TemporaryDirectory() as directory:
            bin_dir, log = Path(directory), Path(directory) / 'calls'
            (bin_dir / 'omarchy-shell').write_text(f'#!/bin/sh\necho "shell $*" >> {log}\necho {shell_reply}\n')
            (bin_dir / 'wpctl').write_text(f'#!/bin/sh\necho "wpctl $*" >> {log}\n')
            for name in ('omarchy-shell', 'wpctl'):
                (bin_dir / name).chmod(0o755)
            env = {**os.environ, 'PATH': f'{bin_dir}:/usr/bin:/bin'}
            result = subprocess.run(['bash', str(SCRIPT), action], env=env, capture_output=True, text=True)
            return result.returncode, log.read_text().splitlines() if log.exists() else []

    def test_the_shell_steps_the_volume_with_its_osd(self):
        code, calls = self.run_keys('raise', 'ok')
        self.assertEqual((code, calls), (0, ['shell -q media volume raise']))

    def test_without_the_shell_wpctl_steps_it(self):
        code, calls = self.run_keys('lower', 'unhandled')
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], 'wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%-')
        code, calls = self.run_keys('mute-toggle', '')
        self.assertEqual(calls[-1], 'wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle')

    def test_the_volume_keys_are_bound_to_volume(self):
        rc = (PROJECT / 'desktop/shell/labwc-rc.xml').read_text()
        for key, action in (('XF86AudioRaiseVolume', 'raise'), ('XF86AudioLowerVolume', 'lower')):
            block = rc[rc.index(f'<keybind key="{key}">'):]
            self.assertIn(f'omarchy-volume {action}', block[:block.index('</keybind>')])

    def test_a_new_output_starts_at_ten_percent(self):
        conf = (PROJECT / 'system/overlay/etc/wireplumber/wireplumber.conf.d/60-omarchy-a-volume.conf').read_text()
        self.assertIn('device.routes.default-sink-volume = 0.001', conf)  # 0.1 on the cubic scale

    def test_the_bar_has_the_audio_mixer(self):
        self.assertIn('"omarchy.audio"', (PROJECT / 'desktop/shell/config/omarchy/shell.json').read_text())


if __name__ == '__main__':
    unittest.main()
