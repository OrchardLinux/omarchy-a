"""Display scale: upstream's omarchy-hyprland-monitor-scaling/-persist on wlr-randr, and login's scale-output."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from release import public_root

PROJECT = Path(__file__).resolve().parents[1]
BIN = PROJECT / 'desktop/shell/bin'
SCALE_OUTPUT = PROJECT / 'desktop/configuration/scale-output'
MODEL = PROJECT / 'desktop/shell/shell/plugins/panels/monitor/Model.js'
BASH = shutil.which('bash')

RANDR = '''#!/bin/sh
if [ "$1" = "--json" ]; then
  cat "$RANDR_JSON"
elif [ "$#" -eq 0 ]; then
  cat "$RANDR_TEXT"
else
  echo "$*" >> "$RANDR_LOG"
fi
'''
# Not every host date knows --iso-8601; the log only needs a timestamp.
DATE = '#!/bin/sh\necho 2026-11-14T00:00:00+00:00\n'

PRESETS = ('1', '1.25', '1.6', '2', '3', '4')
CLEAN = {(1536, 2048): ('1', '1.33333', '1.6', '2', '3.2', '4'),
         (1620, 2160): ('1', '1.25', '1.66667', '2', '3', '4')}


def randr_json(width, height, scale, name='Unknown-1'):
    return json.dumps([{'name': name, 'enabled': True, 'scale': scale, 'transform': 'normal',
                        'modes': [{'width': width, 'height': height, 'refresh': 60.0,
                                   'preferred': True, 'current': True}]}])


def bash_major():
    out = subprocess.run([BASH, '-c', 'echo ${BASH_VERSINFO[0]}'], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


@unittest.skipUnless(BASH and shutil.which('jq') and bash_major() >= 4, 'bash 4+ and jq are needed')
class Scaling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        stubs = self.root / 'stubs'
        stubs.mkdir()
        for name, body in (('wlr-randr', RANDR), ('date', DATE)):
            (stubs / name).write_text(body)
            (stubs / name).chmod(0o755)
        self.state = self.root / 'state'
        self.log = self.root / 'randr.log'
        self.json = self.root / 'randr.json'
        self.env = {**os.environ, 'PATH': f'{stubs}:{BIN}:{os.environ["PATH"]}',
                    'XDG_STATE_HOME': str(self.state), 'RANDR_LOG': str(self.log), 'RANDR_JSON': str(self.json)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_command(self, *args, check=True):
        return subprocess.run([BASH, str(BIN / args[0]), *args[1:]], env=self.env, capture_output=True,
                              text=True, check=check)

    def scale(self, *args):
        self.log.unlink(missing_ok=True)
        self.run_command('omarchy-hyprland-monitor-scaling', *args)
        return self.log.read_text().splitlines()

    def settings(self):
        return (self.state / 'omarchy/monitors/settings').read_text().splitlines()

    def test_presets_round_up_to_scales_the_mode_divides_into(self):
        for (width, height), expected in CLEAN.items():
            self.json.write_text(randr_json(width, height, 2))
            applied = [self.scale(preset)[0] for preset in PRESETS]
            self.assertEqual(applied, ['--output Unknown-1 --scale ' + s for s in expected], (width, height))

    def test_up_and_down_step_through_distinct_scales(self):
        self.json.write_text(randr_json(1536, 2048, 2))
        self.assertEqual(self.scale('up'), ['--output Unknown-1 --scale 3.2'])
        self.assertEqual(self.scale('down'), ['--output Unknown-1 --scale 1.6'])
        self.json.write_text(randr_json(1536, 2048, 4))
        self.assertEqual(self.scale('up'), ['--output Unknown-1 --scale 4'])
        self.json.write_text(randr_json(1536, 2048, 1))
        self.assertEqual(self.scale('down'), ['--output Unknown-1 --scale 1'])

    def test_shows_the_scale_and_refuses_unknown_monitors_and_values(self):
        self.json.write_text(randr_json(1620, 2160, 1.666667))
        self.assertEqual(self.run_command('omarchy-hyprland-monitor-scaling').stdout, '1.66667\n')
        missing = self.run_command('omarchy-hyprland-monitor-scaling', '--monitor', 'DP-9', '2', check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('No such monitor: DP-9', missing.stderr)
        self.assertNotEqual(self.run_command('omarchy-hyprland-monitor-scaling', '5', check=False).returncode, 0)
        self.assertFalse(self.log.exists())

    def test_a_change_is_saved_per_monitor_and_logged(self):
        self.json.write_text(randr_json(1536, 2048, 2))
        self.scale('--monitor', 'Unknown-1', '1.25')
        self.assertEqual(self.settings(), ['\t\t1.33333\t\tUnknown-1'])
        entry = dict(field.split('=', 1) for field in
                     (self.state / 'omarchy/monitors/scaling').read_text().splitlines()[0].split('\t'))
        self.assertEqual((entry['requested'], entry['current'], entry['new'], entry['monitor']),
                         ('1.25', '2', '1.33333', 'Unknown-1'))

    def test_persist_keeps_other_monitors_and_the_saved_mode_position_and_transform(self):
        settings = self.state / 'omarchy/monitors/settings'
        settings.parent.mkdir(parents=True)
        settings.write_text('1536x2048@60\t0x0\t2\t1\tUnknown-1\n2560x1440@60\t1536x0\t1\t\tDP-1\n')
        self.run_command('omarchy-hyprland-monitor-persist', 'Unknown-1', '1.6')
        self.assertEqual(self.settings(), ['2560x1440@60\t1536x0\t1\t\tDP-1', '1536x2048@60\t0x0\t1.6\t1\tUnknown-1'])
        self.run_command('omarchy-hyprland-monitor-persist', 'Unknown-1', '2', '2048x1536@60', '', '3')
        self.assertEqual(self.settings()[-1], '2048x1536@60\t0x0\t2\t3\tUnknown-1')
        refused = self.run_command('omarchy-hyprland-monitor-persist', 'bad name', '2', check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(len(self.settings()), 2)


@unittest.skipUnless(BASH and bash_major() >= 4, 'bash 4+ is needed')
class ScaleOutput(unittest.TestCase):
    def run_script(self, mode='1536x2048', settings=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs = root / 'stubs'
            stubs.mkdir()
            (stubs / 'wlr-randr').write_text(RANDR)
            (stubs / 'wlr-randr').chmod(0o755)
            text = root / 'randr.txt'
            text.write_text(f'Unknown-1 "Apple panel"\n  Enabled: yes\n  Modes:\n'
                            f'    {mode} px, 60.000000 Hz (preferred, current)\n')
            state = root / 'state'
            if settings is not None:
                (state / 'omarchy/monitors').mkdir(parents=True)
                (state / 'omarchy/monitors/settings').write_text(settings)
            log = root / 'randr.log'
            env = {**os.environ, 'PATH': f'{stubs}:{os.environ["PATH"]}', 'XDG_STATE_HOME': str(state),
                   'RANDR_LOG': str(log), 'RANDR_TEXT': str(text)}
            subprocess.run([BASH, str(SCALE_OUTPUT)], env=env, check=True, capture_output=True)
            return log.read_text().splitlines() if log.exists() else []

    def test_nothing_saved_scales_the_native_panel_by_two(self):
        self.assertEqual(self.run_script(), ['--output Unknown-1 --scale 2'])
        self.assertEqual(self.run_script(settings='\t\t1.6\t\tDP-1\n'), ['--output Unknown-1 --scale 2'])

    def test_the_saved_scale_for_the_panel_wins(self):
        self.assertEqual(self.run_script(mode='2160x1620', settings='\t\t1.66667\t\tUnknown-1\n'),
                         ['--output Unknown-1 --scale 1.66667'])

    def test_an_unusable_saved_scale_falls_back_to_two(self):
        self.assertEqual(self.run_script(settings='\t\t9\t\tUnknown-1\n'), ['--output Unknown-1 --scale 2'])
        self.assertEqual(self.run_script(settings='\t\t$(x)\t\tUnknown-1\n'), ['--output Unknown-1 --scale 2'])

    def test_other_modes_are_left_alone(self):
        self.assertEqual(self.run_script(mode='1280x800', settings='\t\t1\t\tUnknown-1\n'), [])


@unittest.skipUnless(shutil.which('node'), 'Node is needed to execute the QML JavaScript functions')
class PanelModel(unittest.TestCase):
    def test_pills_offer_one_preset_per_clean_scale_with_its_label(self):
        script = ('const m = require(process.argv[1]); const p = ["1","1.25","1.6","2","3","4"];'
                  'const out = {}; for (const [w, h] of [[1536, 2048], [1620, 2160]]) {'
                  'out[w] = m.availableScales(p, w, h).map(s => m.cleanScale(s, w, h)); }'
                  'out.index = m.matchingScaleIndex(m.availableScales(p, 1536, 2048), 3.2, 1536, 2048);'
                  'console.log(JSON.stringify(out))')
        result = subprocess.run(['node', '-e', script, str(MODEL)], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), {'1536': ['1', '1.33', '1.6', '2', '3.2', '4'],
                                                     '1620': ['1', '1.25', '1.67', '2', '3', '4'], 'index': 4})


class Packaging(unittest.TestCase):
    def test_keys_panel_and_root_use_the_command(self):
        tree = ET.parse(PROJECT / 'desktop/shell/labwc-rc.xml')
        for key, direction in (('W-slash', 'up'), ('W-A-slash', 'down')):
            command = tree.find("./keyboard/keybind[@key='%s']/action" % key).get('command')
            self.assertEqual(command, 'omarchy-hyprland-monitor-scaling ' + direction)
        panel = (PROJECT / 'desktop/shell/shell/plugins/panels/monitor/Panel.qml').read_text()
        self.assertIn('"omarchy-hyprland-monitor-scaling", "--monitor"', panel)
        self.assertIn('Commons.I18n.t("monitor.scale")', panel)
        additions, links = public_root.desktop_additions(), public_root.desktop_links()
        for command in ('omarchy-hyprland-monitor-scaling', 'omarchy-hyprland-monitor-persist'):
            path = 'home/tablet/.local/share/omarchy-ipad/bin/' + command
            self.assertEqual(additions[path], ((BIN / command).read_bytes(), 0o755))
            self.assertEqual(links['usr/local/bin/' + command], '/' + path)
        replacements = public_root.desktop_replacements()
        self.assertEqual(replacements['usr/local/libexec/arch-ipad-scale-output'], SCALE_OUTPUT.read_bytes())
        self.assertIn('home/tablet/.local/share/omarchy-ipad/shell/plugins/panels/monitor/Panel.qml', replacements)


if __name__ == '__main__':
    unittest.main()
