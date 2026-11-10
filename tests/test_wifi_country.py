"""The Wi-Fi country is remembered when Wi-Fi comes up and set again at the next boot."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
HOOK = PROJECT / 'system/overlay/etc/NetworkManager/dispatcher.d/60-omarchy-a-wifi-country'
UNIT = PROJECT / 'system/overlay/usr/lib/systemd/system/omarchy-wifi-country.service'


class WifiCountry(unittest.TestCase):
    def run_hook(self, reg, iface='wld0', action='up'):
        with tempfile.TemporaryDirectory() as root:
            iw = Path(root) / 'iw'
            iw.write_text(f'#!/bin/sh\nprintf "{reg}"\n')
            iw.chmod(0o755)
            state = Path(root) / 'state'
            script = HOOK.read_text().replace('/usr/bin/iw', str(iw)).replace('/var/lib/omarchy-a', str(state))
            subprocess.run(['sh', '-c', script, 'hook', iface, action], check=True,
                           env={**os.environ, 'DEVICE_IFACE': iface})
            saved = state / 'wifi-country'
            return saved.read_text() if saved.exists() else None

    def test_the_announced_country_is_saved_on_wifi_up(self):
        self.assertEqual(self.run_hook('global\\ncountry ID: DFS-UNSET\\n'), 'ID\n')

    def test_the_world_domain_usb_and_other_events_save_nothing(self):
        self.assertIsNone(self.run_hook('global\\ncountry 00: DFS-UNSET\\n'))
        self.assertIsNone(self.run_hook('global\\ncountry ID: DFS-UNSET\\n', iface='usb0'))
        self.assertIsNone(self.run_hook('global\\ncountry ID: DFS-UNSET\\n', action='down'))

    def test_the_boot_unit_runs_before_networkmanager_and_is_enabled(self):
        unit = UNIT.read_text()
        self.assertIn('Before=NetworkManager.service', unit)
        self.assertIn('ConditionPathExists=/var/lib/omarchy-a/wifi-country', unit)
        self.assertIn("'omarchy-wifi-country.service'", (PROJECT / 'release/public_root.py').read_text())
        self.assertTrue(os.access(HOOK, os.X_OK))

    def test_the_image_installs_the_hook_executable(self):
        # NetworkManager runs only executable dispatcher scripts.
        import sys
        sys.path.insert(0, str(PROJECT))
        from release import public_root
        files = public_root.system_files()
        self.assertEqual(files['etc/NetworkManager/dispatcher.d/60-omarchy-a-wifi-country'][1], 0o755)


if __name__ == '__main__':
    unittest.main()
