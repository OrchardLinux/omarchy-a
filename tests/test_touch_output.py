"""desktop/configuration/touch-output: touchscreens mapped to the connected panel."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'desktop/configuration/touch-output'


class TouchOutput(unittest.TestCase):
    def run_script(self, connectors, inputs):
        with tempfile.TemporaryDirectory() as tmp:
            sys_root = Path(tmp) / 'sys'
            for name, status in connectors.items():
                d = sys_root / 'class/drm' / name
                d.mkdir(parents=True)
                (d / 'status').write_text(status + '\n')
            for i, (name, props) in enumerate(inputs):
                d = sys_root / f'class/input/input{i}'
                d.mkdir(parents=True)
                (d / 'name').write_text(name + '\n')
                (d / 'properties').write_text(props + '\n')
            out = Path(tmp) / 'config/labwc/rc.xml'
            subprocess.run(['bash', str(SCRIPT), str(out)], env={**os.environ, 'SYSFS_ROOT': str(sys_root)},
                           check=True, timeout=20)
            return out.read_text() if out.exists() else None

    def test_touchscreens_follow_the_connected_panel(self):
        xml = self.run_script({'card0-Unknown-1': 'connected', 'card0-HDMI-A-1': 'disconnected'},
                              [('gpio-keys', '0'), ('iPad7,5 Touchscreen', '2')])
        self.assertEqual(xml, '<?xml version="1.0"?>\n<labwc_config>\n'
                              '  <touch deviceName="iPad7,5 Touchscreen" mapToOutput="Unknown-1" '
                              'mouseEmulation="no" />\n</labwc_config>\n')

    def test_names_are_escaped(self):
        xml = self.run_script({'card0-eDP-1': 'connected'}, [('A & "B" <touch>', '2')])
        self.assertIn('deviceName="A &amp; &quot;B&quot; &lt;touch&gt;" mapToOutput="eDP-1"', xml)

    def test_nothing_without_a_panel_or_a_touchscreen(self):
        self.assertIsNone(self.run_script({'card0-eDP-1': 'disconnected'}, [('Touch', '2')]))
        self.assertIsNone(self.run_script({'card0-eDP-1': 'connected'}, [('gpio-keys', '0')]))


if __name__ == '__main__':
    unittest.main()
