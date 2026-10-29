import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-toggle-bar'


class BarToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home, self.runtime, stubs = root / 'home', root / 'run', root / 'bin'
        for path in (self.home, self.runtime, stubs):
            path.mkdir()
        self.calls = root / 'calls'
        stub = stubs / 'omarchy-shell'
        stub.write_text('#!/bin/sh\necho "$@" >> %s\n' % self.calls)
        stub.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.home), 'XDG_RUNTIME_DIR': str(self.runtime),
                    'PATH': '%s:%s' % (stubs, os.environ['PATH'])}
        self.flag = self.home / '.local/state/omarchy/toggles/bar-off'

    def toggle(self):
        subprocess.run(['bash', str(SCRIPT)], env=self.env, check=True)

    def test_toggle_flips_the_flag_and_asks_the_bar_to_resync(self):
        self.toggle()
        self.assertTrue(self.flag.exists())
        self.toggle()
        self.assertFalse(self.flag.exists())
        self.assertEqual(self.calls.read_text().splitlines(), ['-q omarchy.bar syncHidden'] * 2)

    def test_super_shift_space_runs_the_toggle(self):
        tree = ET.fromstring((PROJECT / 'desktop/shell/labwc-rc.xml').read_bytes())
        bindings = tree.findall("./keyboard/keybind[@key='W-S-space']")
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].find('action').get('command'), 'omarchy-toggle-bar')

    def test_hidden_bar_is_unmapped_not_parked(self):
        # labwc never un-parks a layer surface whose margin returns to 0.
        bar = (PROJECT / 'desktop/shell/shell/plugins/bar/Bar.qml').read_text()
        self.assertIn('visible: !root.barHidden && !remapGuard.remapping', bar)
