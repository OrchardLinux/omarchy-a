"""desktop/configuration/rotate-output: iio-sensor-proxy orientations to output transforms."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'desktop/configuration/rotate-output'

RANDR = '''#!/bin/sh
if [ "$#" -eq 0 ]; then
  printf 'Unknown-1 "Apple panel"\\n  Enabled: yes\\n'
else
  echo "$*" >> "$RANDR_LOG"
fi
'''


def monitor(events):
    """A monitor-sensor stand-in: (delay before the line in seconds, line)."""
    lines = ['#!/bin/sh', "echo '    Waiting for iio-sensor-proxy to appear'"]
    for delay, line in events:
        lines += [f'sleep {delay}', f"echo '{line}'"]
    return '\n'.join(lines) + '\n'


BASH = shutil.which('bash')


def bash_major():
    out = subprocess.run([BASH, '-c', 'echo ${BASH_VERSINFO[0]}'], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


@unittest.skipUnless(BASH and bash_major() >= 4, 'needs bash 4+ (fractional read -t), as on the device')
class RotateOutput(unittest.TestCase):
    def run_script(self, events, locked=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            for name, body in (('monitor-sensor', monitor(events)), ('wlr-randr', RANDR)):
                (bin_dir / name).write_text(body)
                (bin_dir / name).chmod(0o755)
            config = root / 'config'
            if locked:
                (config / 'omarchy').mkdir(parents=True)
                (config / 'omarchy/rotation-lock').touch()
            log = root / 'randr.log'
            env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}',
                   'XDG_CONFIG_HOME': str(config), 'RANDR_LOG': str(log), 'ROTATE_SETTLE': '0.1'}
            subprocess.run([BASH, str(SCRIPT)], env=env, check=True, timeout=20)
            return log.read_text().splitlines() if log.exists() else []

    def test_held_orientations_become_transforms_of_the_panel(self):
        events = [(0, '=== Has accelerometer (orientation: normal)'),
                  (0.3, '    Accelerometer orientation changed: left-up'),
                  (0.3, '    Accelerometer orientation changed: bottom-up'),
                  (0.3, '    Accelerometer orientation changed: undefined'),
                  (0.3, '    Accelerometer orientation changed: right-up'),
                  (0.3, '    Accelerometer orientation changed: normal')]
        self.assertEqual(self.run_script(events), [
            '--output Unknown-1 --transform normal',
            '--output Unknown-1 --transform 90',
            '--output Unknown-1 --transform 180',
            '--output Unknown-1 --transform 270',
            '--output Unknown-1 --transform normal',
        ])

    def test_passing_through_an_orientation_rotates_once(self):
        events = [(0, '=== Has accelerometer (orientation: normal)'),
                  (0.3, '    Accelerometer orientation changed: left-up'),
                  (0.02, '    Accelerometer orientation changed: bottom-up'),
                  (0.3, '    Accelerometer orientation changed: bottom-up')]
        self.assertEqual(self.run_script(events), [
            '--output Unknown-1 --transform normal',
            '--output Unknown-1 --transform 180',
        ])

    def test_lock_holds_the_orientation(self):
        events = [(0, '=== Has accelerometer (orientation: normal)'),
                  (0.3, '    Accelerometer orientation changed: left-up')]
        self.assertEqual(self.run_script(events, locked=True), [])


if __name__ == '__main__':
    unittest.main()
