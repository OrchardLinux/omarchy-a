from pathlib import Path
import runpy
import tempfile
import unittest
import xml.etree.ElementTree as ET

from release.j71b.public_root import desktop_replacements, system_files


PROJECT = Path(__file__).resolve().parents[1]
HELPER = PROJECT / 'system/j71b/overlay/usr/libexec/omarchy-screen-toggle'
HELPER_NAMESPACE = runpy.run_path(str(HELPER))
toggle = HELPER_NAMESPACE['toggle']
panel = HELPER_NAMESPACE['panel']


class ScreenToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.device = self.root / 'backlight'
        self.device.mkdir()
        (self.device / 'max_brightness').write_text('2047\n')
        (self.device / 'brightness').write_text('731\n')

    def test_panel_is_the_only_backlight(self):
        backlights = self.root / 'class'
        backlights.mkdir()
        with self.assertRaisesRegex(ValueError, 'found 0'):
            panel(backlights)
        (backlights / '20e200000.backlight').mkdir()
        self.assertEqual(panel(backlights).name, '20e200000.backlight')
        (backlights / 'other').mkdir()
        with self.assertRaisesRegex(ValueError, 'found 2'):
            panel(backlights)

    def test_round_trip_restores_exact_raw_brightness(self):
        self.assertEqual(toggle(self.device, self.runtime), 0)
        self.assertEqual((self.device / 'brightness').read_text(), '0\n')
        saved = self.runtime / 'omarchy-screen-brightness'
        self.assertEqual(saved.read_text(), '731\n')
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(toggle(self.device, self.runtime), 731)
        (self.device / 'brightness').write_text('139\n')
        self.assertEqual(toggle(self.device, self.runtime), 0)
        self.assertEqual(toggle(self.device, self.runtime), 139)

    def test_off_without_valid_saved_value_has_visible_fallback(self):
        saved = self.runtime / 'omarchy-screen-brightness'
        for value in (None, 'invalid', '0', '-1', '9999'):
            with self.subTest(value=value):
                (self.device / 'brightness').write_text('0\n')
                if value is None:
                    saved.unlink(missing_ok=True)
                else:
                    saved.write_text(value)
                self.assertEqual(toggle(self.device, self.runtime), 2047 if value == '9999' else 1023)

    def test_unsafe_state_or_runtime_is_rejected_without_blanking(self):
        outside = self.root / 'outside'
        outside.write_text('unchanged')
        (self.runtime / 'omarchy-screen-brightness').symlink_to(outside)
        with self.assertRaises(OSError):
            toggle(self.device, self.runtime)
        self.assertEqual(outside.read_text(), 'unchanged')
        self.assertEqual((self.device / 'brightness').read_text(), '731\n')
        self.runtime.chmod(0o755)
        with self.assertRaises(ValueError):
            toggle(self.device, self.runtime)

    def test_binding_and_executable_are_in_public_root_inputs(self):
        replacements = desktop_replacements()
        tree = ET.fromstring(replacements['home/tablet/.config/labwc/rc.xml'])
        bindings = tree.findall("./keyboard/keybind[@key='XF86PowerOff']")
        self.assertEqual(len(bindings), 1)
        binding = bindings[0]
        self.assertEqual(binding.get('onRelease'), 'yes')
        self.assertEqual(binding.get('allowWhenLocked'), 'yes')
        # The power key locks before blanking; omarchy-tablet-power drives the toggle helper.
        self.assertEqual(binding.find('action').attrib,
                         {'name': 'Execute', 'command': 'omarchy-tablet-power power'})
        self.assertEqual(system_files('test')['usr/libexec/omarchy-screen-toggle'],
                         (HELPER.read_bytes(), 0o755))
