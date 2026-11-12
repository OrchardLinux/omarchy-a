"""The system opts in through data, leaving USB ownership to the initrd."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class MacUsbCurrent(unittest.TestCase):
    def test_profile_is_exact_opt_in_for_matching_hardware(self):
        self.assertEqual((ROOT/'system/overlay/etc/orchard/mac-usb-current').read_bytes(), b'1\n')
        self.assertIn('freshly matched initrd', (ROOT/'docs/power-and-lock.md').read_text())

    def test_system_root_includes_the_opt_in(self):
        from release.public_root import system_files
        data, mode = system_files()['etc/orchard/mac-usb-current']
        self.assertEqual((data, mode), (b'1\n', 0o644))

if __name__ == '__main__':
    unittest.main()
