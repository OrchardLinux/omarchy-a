"""The package applies wvkbd-0.20-layout.patch, the result of friendly-layout.py: the two must agree.

Needs a wvkbd v0.20 source tree (WVKBD_SOURCE, the release archive unpacked); skipped without one.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

KEYBOARD = Path(__file__).resolve().parents[1] / 'desktop/keyboard'
SOURCE = os.environ.get('WVKBD_SOURCE')


@unittest.skipUnless(SOURCE and shutil.which('patch') and shutil.which('diff'), 'set WVKBD_SOURCE to a wvkbd v0.20 tree')
class LayoutPatch(unittest.TestCase):
    def test_the_patch_is_the_generators_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(SOURCE, root / 'patched')
            subprocess.run(['patch', '-s', '--batch', '--fuzz=0', '-d', str(root / 'patched'), '-p1'],
                           stdin=(KEYBOARD / 'wvkbd-0.20.patch').open(), check=True)
            shutil.copytree(root / 'patched', root / 'generated')
            shutil.copytree(root / 'patched', root / 'applied')
            subprocess.run([sys.executable, str(KEYBOARD / 'friendly-layout.py'), str(root / 'generated')], check=True)
            subprocess.run(['patch', '-s', '--batch', '--fuzz=0', '-d', str(root / 'applied'), '-p1'],
                           stdin=(KEYBOARD / 'wvkbd-0.20-layout.patch').open(), check=True)
            self.assertEqual(subprocess.run(['diff', '-r', str(root / 'generated'), str(root / 'applied')]).returncode, 0)


if __name__ == '__main__':
    unittest.main()
