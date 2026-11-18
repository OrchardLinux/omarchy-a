"""Upstream's Display panel on labwc: omarchy-monitor-state from wlr-randr."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-monitor-state'
MODEL = PROJECT / 'desktop/shell/shell/plugins/panels/monitor/Model.js'

# What wlr-randr --json says on an iPad (J71b): one panel, connector type unknown.
IPAD = [{"name": "Unknown-1", "description": "", "make": "Apple", "model": "", "serial": "",
         "physical_size": {"width": 148, "height": 197}, "enabled": True,
         "modes": [{"width": 1536, "height": 2048, "refresh": 60.0, "preferred": True, "current": True}],
         "position": {"x": 0, "y": 0}, "transform": "90", "scale": 2.0, "adaptive_sync": False}]


@unittest.skipUnless(shutil.which('jq'), 'omarchy-monitor-state uses jq')
class MonitorStateTests(unittest.TestCase):
    def run_state(self, outputs, brightness='63'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'outputs.json').write_text(json.dumps(outputs))
            stubs = {'wlr-randr': f'cat {root}/outputs.json\n',
                     'omarchy-brightness-display': f'echo {brightness}\n'}
            for name, body in stubs.items():
                (root / name).write_text('#!/bin/sh\n' + body)
                (root / name).chmod(0o755)
            # The scale comes from the command beside the script; run a copy whose neighbour is a stub.
            shutil.copy(SCRIPT, root / 'omarchy-monitor-state')
            (root / 'omarchy-hyprland-monitor-scaling').write_text('#!/bin/sh\necho 2\n')
            (root / 'omarchy-hyprland-monitor-scaling').chmod(0o755)
            env = {**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}'}
            result = subprocess.run(['bash', str(root / 'omarchy-monitor-state')], env=env,
                                    capture_output=True, text=True, check=True)
            return result.stdout.split('\n')

    def test_the_lines_the_panel_reads(self):
        lines = self.run_state(IPAD)
        self.assertEqual(lines[0], '63')               # the shown display's brightness
        self.assertEqual(lines[1], 'Unknown-1')        # the built-in panel
        self.assertEqual(lines[2], '')                 # no external display
        self.assertEqual(lines[3], 'Unknown-1')        # the built-in panel is on
        self.assertEqual(lines[4], '')                 # nothing mirrored
        self.assertEqual(lines[5], 'Unknown-1')        # labwc has no focus: the first enabled output
        self.assertEqual(lines[6], '2')
        displays = json.loads(lines[7])
        self.assertEqual(displays, [{
            'name': 'Unknown-1', 'make': 'Apple', 'model': '', 'enabled': True, 'focused': True,
            'width': 1536, 'height': 2048, 'physicalWidth': 148, 'physicalHeight': 197,
            'refreshRate': 60.0, 'scale': 2.0, 'x': 0, 'y': 0, 'transform': 1, 'mirrorOf': 'none',
            'availableModes': ['1536x2048@60Hz'], 'brightness': 63}])
        self.assertEqual(lines[8], '')                 # no mirror of Omarchy's own

    def test_without_a_backlight_the_display_has_no_brightness(self):
        lines = self.run_state(IPAD, brightness='unavailable')
        self.assertEqual(lines[0], 'unavailable')
        self.assertIsNone(json.loads(lines[7])[0]['brightness'])

    def test_no_outputs(self):
        lines = self.run_state([])
        self.assertEqual(lines[1:6], ['', '', '', '', ''])
        self.assertEqual(json.loads(lines[7]), [])


@unittest.skipUnless(shutil.which('node'), 'the panel model runs in node')
class BuiltInTests(unittest.TestCase):
    def test_an_ipad_panel_is_the_built_in_display(self):
        script = ('const m = require(process.argv[1]);'
                  'console.log(JSON.stringify(["Unknown-1","eDP-1","DSI-1","HDMI-A-1"].map(m.isBuiltIn)));'
                  'console.log(m.displayTitle({name: "Unknown-1", make: "Apple"}, "Built-in Display"))')
        out = subprocess.run(['node', '-e', script, str(MODEL)], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.splitlines(), ['[true,true,true,false]', 'Built-in Display'])


if __name__ == '__main__':
    unittest.main()
