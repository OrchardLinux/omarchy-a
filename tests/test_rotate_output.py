"""desktop/configuration/rotate-output: iio-sensor-proxy orientations to output transforms."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'desktop/configuration/rotate-output'

MONITOR = '''#!/bin/sh
cat <<'OUT'
    Waiting for iio-sensor-proxy to appear
+++ iio-sensor-proxy appeared
=== Has accelerometer (orientation: normal)
    Accelerometer orientation changed: left-up
    Accelerometer orientation changed: bottom-up
    Accelerometer orientation changed: undefined
    Accelerometer orientation changed: right-up
    Accelerometer orientation changed: normal
OUT
'''

RANDR = '''#!/bin/sh
if [ "$#" -eq 0 ]; then
  printf 'eDP-1 "Apple panel"\\n  Enabled: yes\\n'
else
  echo "$*" >> "$RANDR_LOG"
fi
'''


class RotateOutput(unittest.TestCase):
    def run_script(self, locked=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            for name, body in (('monitor-sensor', MONITOR), ('wlr-randr', RANDR)):
                (bin_dir / name).write_text(body)
                (bin_dir / name).chmod(0o755)
            config = root / 'config'
            if locked:
                (config / 'omarchy').mkdir(parents=True)
                (config / 'omarchy/rotation-lock').touch()
            log = root / 'randr.log'
            env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}',
                   'XDG_CONFIG_HOME': str(config), 'RANDR_LOG': str(log)}
            subprocess.run(['bash', str(SCRIPT)], env=env, check=True, timeout=20)
            return log.read_text().splitlines() if log.exists() else []

    def test_orientations_become_transforms_of_the_panel(self):
        self.assertEqual(self.run_script(), [
            '--output eDP-1 --transform normal',
            '--output eDP-1 --transform 90',
            '--output eDP-1 --transform 180',
            '--output eDP-1 --transform 270',
            '--output eDP-1 --transform normal',
        ])

    def test_lock_holds_the_orientation(self):
        self.assertEqual(self.run_script(locked=True), [])


if __name__ == '__main__':
    unittest.main()
