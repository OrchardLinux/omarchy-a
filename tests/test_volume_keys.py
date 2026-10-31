"""The volume keys control the volume, and a new output starts quiet."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-volume'


class VolumeKeys(unittest.TestCase):
    def run_keys(self, action, volume='0.45'):
        """Run omarchy-volume ACTION at VOLUME; returns (exit code, the calls it made)."""
        with tempfile.TemporaryDirectory() as directory:
            bin_dir, log, level = Path(directory), Path(directory) / 'calls', Path(directory) / 'level'
            level.write_text(volume)
            (bin_dir / 'omarchy-shell').write_text(f'#!/bin/sh\necho "shell $*" >> {log}\n')
            # A fake wpctl that keeps the level: set-volume N% stores N/100.
            (bin_dir / 'wpctl').write_text(f"""#!/bin/sh
echo "wpctl $*" >> {log}
case $1 in
  get-volume) echo "Volume: $(cat {level})" ;;
  set-volume) awk -v v="${{3%\\%}}" 'BEGIN {{ printf "%.2f", v / 100 }}' > {level} ;;
esac
""")
            for name in ('omarchy-shell', 'wpctl'):
                (bin_dir / name).chmod(0o755)
            env = {**os.environ, 'PATH': f'{bin_dir}:/usr/bin:/bin'}
            result = subprocess.run(['bash', str(SCRIPT), action], env=env, capture_output=True, text=True)
            return result.returncode, [line for line in log.read_text().splitlines() if 'get-volume' not in line]

    def test_steps_land_on_multiples_of_5(self):
        for action, volume, expected in (('raise', '0.45', '50%'), ('raise', '0.12', '15%'),
                                         ('lower', '0.12', '10%'), ('lower', '0.45', '40%'),
                                         ('raise', '0.98', '100%'), ('lower', '0.03', '0%')):
            with self.subTest(action=action, volume=volume):
                code, calls = self.run_keys(action, volume)
                self.assertEqual(code, 0)
                self.assertEqual(calls[0], f'wpctl set-volume @DEFAULT_AUDIO_SINK@ {expected}')
                self.assertTrue(calls[-1].startswith('shell -q shell summon omarchy.osd '))
                self.assertIn(f'"progressText":"{expected}"', calls[-1])

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
