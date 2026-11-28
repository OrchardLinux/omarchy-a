"""Display rotation by hand: omarchy-hyprland-monitor-rotate on wlr-randr, the Display panel's
Rotation row, and the saved turn put back at login (rotate-output) where no accelerometer turns the panel."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from package_tree import tree

PROJECT = Path(__file__).resolve().parents[1]
BIN = PROJECT / 'desktop/shell/bin'
ROTATE_OUTPUT = PROJECT / 'desktop/configuration/rotate-output'
PANEL = PROJECT / 'desktop/shell/shell/plugins/panels/monitor/Panel.qml'
BASH = shutil.which('bash')

RANDR = '''#!/bin/sh
if [ "$1" = "--json" ]; then
  cat "$RANDR_JSON"
elif [ "$#" -eq 0 ]; then
  printf 'Unknown-1 "Apple panel"\\n  Enabled: yes\\n'
else
  echo "$*" >> "$RANDR_LOG"
fi
'''
DATE = '#!/bin/sh\necho 2026-11-26T00:00:00+00:00\n'


def randr_json(transform='normal', scale=2, name='Unknown-1', width=1536, height=2048):
    return json.dumps([{'name': name, 'enabled': True, 'scale': scale, 'transform': transform,
                        'modes': [{'width': width, 'height': height, 'refresh': 60.0,
                                   'preferred': True, 'current': True}]}])


def bash_major():
    out = subprocess.run([BASH, '-c', 'echo ${BASH_VERSINFO[0]}'], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


class Stubs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stubs = self.root / 'stubs'
        self.stubs.mkdir()
        for name, body in (('wlr-randr', RANDR), ('date', DATE)):
            (self.stubs / name).write_text(body)
            (self.stubs / name).chmod(0o755)
        self.state = self.root / 'state'
        self.config = self.root / 'config'
        self.log = self.root / 'randr.log'
        self.json = self.root / 'randr.json'
        self.json.write_text(randr_json())
        self.env = {**os.environ, 'PATH': f'{self.stubs}:{BIN}:{os.environ["PATH"]}',
                    'XDG_STATE_HOME': str(self.state), 'XDG_CONFIG_HOME': str(self.config),
                    'RANDR_LOG': str(self.log), 'RANDR_JSON': str(self.json)}
        self.env.pop('LABWC_PID', None)
        self.env.pop('XDG_RUNTIME_DIR', None)

    def tearDown(self):
        self.tmp.cleanup()

    @property
    def settings_file(self):
        return self.state / 'omarchy/monitors/settings'

    def settings(self):
        return self.settings_file.read_text().splitlines() if self.settings_file.exists() else []

    def applied(self):
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        self.log.unlink(missing_ok=True)
        return lines


@unittest.skipUnless(BASH and shutil.which('jq') and bash_major() >= 4, 'bash 4+ and jq are needed')
class RotateCommand(Stubs):
    def rotate(self, *args, check=True):
        return subprocess.run([BASH, str(BIN / 'omarchy-hyprland-monitor-rotate'), *args], env=self.env,
                              capture_output=True, text=True, check=check)

    def test_each_quarter_turn_is_applied_and_saved_for_the_panel(self):
        for degrees, randr, saved in (('90', '90', '1'), ('180', '180', '2'), ('270', '270', '3'), ('0', 'normal', '0')):
            self.rotate(degrees)
            self.assertEqual(self.applied(), [f'--output Unknown-1 --transform {randr}'], degrees)
            self.assertEqual(self.settings(), [f'\t\t2\t{saved}\tUnknown-1'], degrees)
            self.json.write_text(randr_json(randr))

    def test_shows_the_turn_in_degrees(self):
        for transform, shown in (('normal', '0'), ('90', '90'), ('270', '270'), ('flipped-90', 'flipped')):
            self.json.write_text(randr_json(transform))
            self.assertEqual(self.rotate().stdout, shown + '\n', transform)
        self.assertEqual(self.applied(), [])
        self.assertEqual(self.settings(), [])

    def test_the_turn_it_already_has_is_saved_without_a_mode_set(self):
        # A redraw is a full software repaint on the A7's simpledrm: none for nothing.
        self.json.write_text(randr_json('90'))
        self.rotate('--monitor', 'Unknown-1', '90')
        self.assertEqual(self.applied(), [])
        self.assertEqual(self.settings(), ['\t\t2\t1\tUnknown-1'])

    def test_refuses_unknown_monitors_and_values(self):
        missing = self.rotate('--monitor', 'DP-9', '90', check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('No such monitor: DP-9', missing.stderr)
        for value in ('45', '-90', 'left', '360'):
            self.assertNotEqual(self.rotate(value, check=False).returncode, 0, value)
        self.assertNotEqual(self.rotate('--monitor', check=False).returncode, 0)
        self.assertEqual(self.applied(), [])
        self.assertEqual(self.settings(), [])

    def test_the_saved_scale_mode_and_other_monitors_stay(self):
        self.settings_file.parent.mkdir(parents=True)
        self.settings_file.write_text('2560x1440@60\t1536x0\t1\t\tDP-1\n1536x2048@60\t0x0\t1.33333\t\tUnknown-1\n')
        self.json.write_text(randr_json(scale=1.333333))
        self.rotate('270')
        self.assertEqual(self.settings(), ['2560x1440@60\t1536x0\t1\t\tDP-1', '1536x2048@60\t0x0\t1.33333\t3\tUnknown-1'])
        # A scale change afterwards keeps the turn.
        subprocess.run([BASH, str(BIN / 'omarchy-hyprland-monitor-scaling'), '1.6'], env=self.env,
                       capture_output=True, text=True, check=True)
        self.assertEqual(self.settings()[-1], '1536x2048@60\t0x0\t1.6\t3\tUnknown-1')

    def test_persist_is_found_without_the_session_path(self):
        # Over ssh neither /usr/local/bin nor the shell's bin directory is on PATH.
        self.env['PATH'] = (f'{self.stubs}:/usr/local/bin:/usr/bin:/bin:{Path(BASH).parent}:'
                            f'{Path(shutil.which("jq")).parent}')
        self.assertIsNone(shutil.which('omarchy-hyprland-monitor-persist', path=self.env['PATH']))
        self.rotate('90')
        self.assertEqual(self.applied(), ['--output Unknown-1 --transform 90'])
        self.assertEqual(self.settings(), ['\t\t2\t1\tUnknown-1'])


class LoginRestore(Stubs):
    """rotate-output at login: the saved turn where no accelerometer turns the panel."""

    def run_rotate_output(self, saved=None, accelerometer=False, locked=False, events=()):
        if saved is not None:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(saved)
        lines = ['#!/bin/sh', "echo '    Waiting for iio-sensor-proxy to appear'"]
        lines += [f"sleep {delay}\necho '{line}'" for delay, line in events]
        (self.stubs / 'monitor-sensor').write_text('\n'.join(lines) + '\n')
        (self.stubs / 'monitor-sensor').chmod(0o755)
        accel = self.root / 'iio:device0'
        if accelerometer:
            accel.mkdir(exist_ok=True)
            for axis in 'xyz':
                (accel / f'in_accel_{axis}_raw').write_text('0\n')
        if locked:
            (self.config / 'omarchy').mkdir(parents=True, exist_ok=True)
            (self.config / 'omarchy/rotation-lock').touch()
        env = {**self.env, 'ROTATE_ACCEL': str(accel), 'ROTATE_SETTLE': '0.1', 'ROTATE_COOLDOWN': '0'}
        result = subprocess.run([sys.executable, str(ROTATE_OUTPUT)], env=env, capture_output=True,
                                text=True, check=True, timeout=20)
        return self.applied(), result.stdout

    def test_without_an_accelerometer_the_saved_turn_comes_back(self):
        applied, out = self.run_rotate_output('1536x2048@60\t0x0\t2\t1\tUnknown-1\n')
        self.assertEqual(applied, ['--output Unknown-1 --transform 90'])
        self.assertIn('rotation restored: Unknown-1 -> 90', out)
        for saved, randr in (('2', '180'), ('3', '270')):
            self.assertEqual(self.run_rotate_output(f'\t\t2\t{saved}\tUnknown-1\n')[0],
                             [f'--output Unknown-1 --transform {randr}'])

    def test_back_to_normal_is_restored_too(self):
        self.json.write_text(randr_json('90'))
        self.assertEqual(self.run_rotate_output('\t\t2\t0\tUnknown-1\n')[0], ['--output Unknown-1 --transform normal'])

    def test_nothing_happens_when_the_panel_already_has_it_or_nothing_is_saved(self):
        self.json.write_text(randr_json('270'))
        self.assertEqual(self.run_rotate_output('\t\t2\t3\tUnknown-1\n')[0], [])
        self.json.write_text(randr_json())
        self.settings_file.unlink()
        self.assertEqual(self.run_rotate_output()[0], [])
        # A line saved before rotation was (no transform), another output's, a bad value.
        for saved in ('\t\t2\tUnknown-1\n', '\t\t2\t\tUnknown-1\n', '\t\t1\t1\tDP-1\n', '\t\t2\t9\tUnknown-1\n',
                      '\t\t2\t$(x)\tUnknown-1\n'):
            self.assertEqual(self.run_rotate_output(saved)[0], [], saved)

    def test_an_accelerometer_decides_unless_the_lock_holds_the_turn(self):
        events = [(0, '=== Has accelerometer (orientation: normal)')]
        saved = '\t\t2\t1\tUnknown-1\n'
        # Unlocked, the sensor's orientation is what is applied.
        self.assertEqual(self.run_rotate_output(saved, accelerometer=True, events=events)[0],
                         ['--output Unknown-1 --transform normal'])
        # Locked, the saved turn comes back and the sensor is held off.
        self.assertEqual(self.run_rotate_output(saved, accelerometer=True, locked=True, events=events)[0],
                         ['--output Unknown-1 --transform 90'])

    def test_an_unreadable_output_list_does_not_stop_rotation(self):
        self.json.write_text('not json')
        applied, out = self.run_rotate_output('\t\t2\t1\tUnknown-1\n')
        self.assertEqual(applied, [])
        self.assertIn('rotation restore failed', out)


class Packaging(unittest.TestCase):
    def test_the_panel_offers_the_turns_to_a_finger(self):
        panel = PANEL.read_text()
        self.assertIn('readonly property bool rotateAvailable: true', panel)
        self.assertIn('runAction(["omarchy-hyprland-monitor-rotate", "--monitor", name, String(degrees)])', panel)
        self.assertIn('if (current && rotateAvailable) list.push("rotation")', panel)
        self.assertIn('Commons.I18n.t("monitor.rotation")', panel)
        self.assertIn('onClicked: if (root.current) root.setRotation(root.current.name, degrees)', panel)
        # The rotate menu and the row offer the same turns.
        self.assertEqual(panel.count('model: root.rotationOptions'), 2)
        texts = json.loads((PROJECT / 'desktop/shell/default/i18n/en/shell.json').read_text())
        for key in ('monitor.rotation', 'monitor.rotateNormal', 'monitor.rotate90', 'monitor.rotate180', 'monitor.rotate270'):
            self.assertIn(key, texts)

    def test_the_command_ships_and_is_on_path(self):
        held = [line.split('\t')[0] for line in (PROJECT / 'desktop/upstream-commands-held').read_text().splitlines()]
        self.assertNotIn('omarchy-hyprland-monitor-rotate', held)
        self.assertTrue(os.access(BIN / 'omarchy-hyprland-monitor-rotate', os.X_OK))
        if shutil.which('bash'):
            target = tree()
            shipped = target / 'usr/share/omarchy/bin/omarchy-hyprland-monitor-rotate'
            self.assertEqual(shipped.read_bytes(), (BIN / 'omarchy-hyprland-monitor-rotate').read_bytes())
            self.assertEqual(os.readlink(target / 'usr/bin/omarchy-hyprland-monitor-rotate'),
                             '/usr/share/omarchy/bin/omarchy-hyprland-monitor-rotate')

    def test_login_starts_the_restore_before_the_shell(self):
        autostart = (PROJECT / 'desktop/shell/default/labwc/autostart').read_text()
        self.assertLess(autostart.index('/usr/libexec/arch-ipad-rotate-output'), autostart.index('qs -p'))


if __name__ == '__main__':
    unittest.main()
