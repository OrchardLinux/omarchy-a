"""desktop/configuration/rotate-output: iio-sensor-proxy orientations to output transforms."""
import os
import sys
import runpy
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
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


class RotateOutput(unittest.TestCase):
    def run_script(self, events, locked=False, extra_env=None, timeout=20):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            body = events if isinstance(events, str) else monitor(events)
            for name, body in (('monitor-sensor', body), ('wlr-randr', RANDR)):
                (bin_dir / name).write_text(body)
                (bin_dir / name).chmod(0o755)
            config = root / 'config'
            if locked:
                (config / 'omarchy').mkdir(parents=True)
                (config / 'omarchy/rotation-lock').touch()
            log = root / 'randr.log'
            env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}',
                   'XDG_CONFIG_HOME': str(config), 'RANDR_LOG': str(log), 'ROTATE_SETTLE': '0.1',
                   'ROTATE_COOLDOWN': '0',
                   **(extra_env or {})}
            subprocess.run([sys.executable, str(SCRIPT)], env=env, check=True, timeout=timeout)
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


    def test_ends_with_the_compositor(self):
        # monitor-sensor never ends by itself; the helper must stop it once
        # the compositor is gone instead of outliving the session
        sensor = ("#!/bin/sh\necho '=== Has accelerometer (orientation: normal)'\n"
                  "exec sleep 60\n")
        compositor = subprocess.Popen(['sleep', '1'])
        # reap it as soon as it exits, as the session manager reaps labwc
        reaper = threading.Thread(target=compositor.wait)
        reaper.start()
        try:
            lines = self.run_script(sensor, extra_env={'LABWC_PID': str(compositor.pid)},
                                    timeout=10)
        finally:
            reaper.join()
        self.assertEqual(lines, ['--output Unknown-1 --transform normal'])

    def test_sensor_reader_ending_inside_a_session_is_restarted(self):
        # At login iio-sensor-proxy may not answer yet: the first reader ends
        # at once. Rotation must come back without a new login.
        sensor = ('#!/bin/sh\nif [ ! -e "$RANDR_LOG.started" ]; then : > "$RANDR_LOG.started"; exit 1; fi\n'
                  "echo '=== Has accelerometer (orientation: left-up)'\nexec sleep 60\n")
        compositor = subprocess.Popen(['sleep', '4'])
        reaper = threading.Thread(target=compositor.wait)
        reaper.start()
        try:
            lines = self.run_script(sensor, extra_env={'LABWC_PID': str(compositor.pid)},
                                    timeout=15)
        finally:
            reaper.join()
        self.assertEqual(lines, ['--output Unknown-1 --transform 90'])


class RotationPolicy(unittest.TestCase):
    def test_monitor_sensor_tilt_suffix_is_not_part_of_orientation(self):
        parse = runpy.run_path(str(SCRIPT))['orientation']
        self.assertEqual(parse('=== Has accelerometer (orientation: normal, tilt: face-up)'), 'normal')
        self.assertEqual(parse('Accelerometer orientation changed: left-up, tilt: upright'), 'left-up')
        self.assertEqual(parse('Accelerometer orientation changed: undefined'), 'undefined')
        self.assertIsNone(parse('Accelerometer tilt changed: face-up'))

    def policy(self):
        return runpy.run_path(str(SCRIPT))['Orientation']()

    def test_repeated_messages_do_not_restart_stability_window(self):
        p = self.policy()
        p.observe('left-up', 0)
        p.observe('left-up', .3)
        self.assertEqual(p.ready(.41), 'left-up')

    def test_cooldown_stops_flip_flopping(self):
        p = self.policy()
        p.observe('normal', 0)
        p.committed('normal', 1)
        p.observe('left-up', 1.1)
        self.assertIsNone(p.ready(1.6))
        self.assertEqual(p.ready(1.8), 'left-up')

    def test_undefined_cancels_and_unlock_uses_current_reading(self):
        p = self.policy()
        p.observe('left-up', 0)
        p.observe('undefined', .5)
        self.assertIsNone(p.ready(3))
        p.observe('right-up', 4)
        self.assertIsNone(p.ready(5, locked=True))
        self.assertEqual(p.ready(6, locked=False), 'right-up')

    def test_still_turning_holds_a_settled_reading_for_a_bounded_time(self):
        module = type("M", (), runpy.run_path(str(SCRIPT)))
        state = module.Orientation(settle=0.4, cooldown=0, hold=0.6)
        state.observe('left-up', 0.0)
        self.assertEqual(state.ready(0.45, turning=False), 'left-up')
        self.assertIsNone(state.ready(0.45, turning=True))
        state.observe('bottom-up', 0.5)
        self.assertIsNone(state.ready(0.6, turning=True))
        self.assertEqual(state.ready(0.95, turning=False), 'bottom-up')
        # a tablet that never stops moving still rotates
        self.assertEqual(state.ready(1.6, turning=True), 'bottom-up')

    def test_report_lagging_behind_gravity_is_waited_for(self):
        # J71b, 2026-11-10: half turn over the side, gravity at the final
        # orientation at 0.3 s, the proxy still said right-up until 0.9 s later.
        module = type("M", (), runpy.run_path(str(SCRIPT)))
        state = module.Orientation(settle=0.4, cooldown=0, hold=0.6, lag=1.2)
        state.observe('right-up', 0.0)
        self.assertIsNone(state.ready(0.5, facing='normal'))
        self.assertEqual(state.ready(0.5, facing='right-up'), 'right-up')
        self.assertEqual(state.ready(0.5, facing=None), 'right-up')
        self.assertEqual(state.ready(1.7, facing='normal'), 'right-up')
        state.observe('normal', 1.2)
        self.assertEqual(state.ready(1.65, facing='normal'), 'normal')

    def test_facing_follows_the_mount_matrix_and_gives_up_when_never_agreeing(self):
        module = type("M", (), runpy.run_path(str(SCRIPT)))
        motion = module.Turning('/nonexistent')
        motion.matrix = [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]]  # J71b
        for raw, name in (((2000, 65000, 3000), 'normal'), ((1000, -66000, 600), 'bottom-up'),
                          ((57000, -2000, 9000), 'right-up'), ((-60000, 900, 9000), 'left-up')):
            motion.read = lambda raw=raw: raw
            motion.sample(0.0)
            self.assertEqual(motion.trusted_facing(), name)
        for _ in range(3):
            motion.judged('normal')
        self.assertIsNone(motion.trusted_facing())

    def test_turning_is_read_from_the_gravity_angle(self):
        module = type("M", (), runpy.run_path(str(SCRIPT)))
        motion = module.Turning('/nonexistent')
        readings = iter([(65000, 0, 3000), (60000, 25000, 3000), (46000, 46000, 3000)])
        motion.read = lambda: next(readings)
        for now in (0.0, 0.1, 0.2):
            motion.sample(now)
        self.assertTrue(motion.turning())
        still = module.Turning('/nonexistent')
        still.read = lambda: (65000, 200, 3000)
        for now in (0.0, 0.1, 0.2):
            still.sample(now)
        self.assertFalse(still.turning())
        flat = module.Turning('/nonexistent')
        flat.read = lambda: (5000, 1300, 65900)
        for now in (0.0, 0.1, 0.2):
            flat.sample(now)
        self.assertFalse(flat.turning())


if __name__ == '__main__':
    unittest.main()
