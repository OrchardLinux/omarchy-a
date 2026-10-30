import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("rotate", Path(__file__).resolve().parents[1] / "desktop/aop/rotate.py")
rotate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rotate)

OUTPUT = '''DSI-1 "Apple iPad panel"
  Enabled: yes
  Modes:
    1536x2048 px, 60.000 Hz (preferred, current)
  Transform: normal
  Scale: 2.000000
'''
XML = b'''<labwc_config>
<!-- keep my preferences -->
<keyboard><keybind key="W-x"><action name="Close"/></keybind></keyboard>
<libinput><device category="iPad7,5 Touchscreen"><leftHanded>no</leftHanded></device></libinput>
</labwc_config>'''


class RotationTests(unittest.TestCase):
    def test_corner_geometry_and_inverse(self):
        for name, expected in [("normal", (0, 0)), ("90", (1, 0)),
                               ("180", (1, 1)), ("270", (0, 1))]:
            a, b, c, d, e, f = rotate.MATRICES[name]
            self.assertEqual((c, f), expected)
            for x, y in [(0, 0), (1, 0), (0, 1), (1, 1)]:
                self.assertIn((a*x+b*y+c, d*x+e*y+f), [(0, 0), (1, 0), (0, 1), (1, 1)])
        self.assertEqual(rotate.compose(rotate.MATRICES["90"], rotate.MATRICES["270"]),
                         rotate.MATRICES["normal"])

    def test_touch_edit_preserves_unrelated_config_and_comments(self):
        changed = rotate.touch_xml(XML, "iPad7,5 Touchscreen", rotate.MATRICES["90"])
        root = ET.fromstring(changed)
        self.assertEqual(root.find("keyboard/keybind").get("key"), "W-x")
        self.assertEqual(root.find("libinput/device/leftHanded").text, "no")
        self.assertEqual(root.find("libinput/device/calibrationMatrix").text, "0 -1 1 1 0 0")
        self.assertIn(b"keep my preferences", changed)
        self.assertEqual(len(root.findall("libinput/device")), 1)

    def test_namespaced_config_remains_namespaced(self):
        original = b'<labwc_config xmlns="urn:labwc"><keyboard/></labwc_config>'
        changed = rotate.touch_xml(original, "touch", rotate.MATRICES["normal"])
        root = ET.fromstring(changed)
        self.assertIsNotNone(root.find("{urn:labwc}libinput/{urn:labwc}device"))

    def test_existing_calibration_survives_rotation_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "rc.xml")
            baseline = (1.02, 0, -.01, 0, .98, .01)
            path.write_bytes(rotate.touch_xml(XML, "touch", baseline))
            config = {"labwc_config": str(path), "touch_device": "touch"}
            runner = lambda *args: OUTPUT if args == ("wlr-randr",) else ""
            rotate.Controller(config, runner).apply("90")
            self.assertEqual(rotate.Controller(config, runner).baseline, baseline)

    def test_animation_cannot_be_accidentally_reenabled(self):
        with self.assertRaisesRegex(ValueError, "stutters"):
            rotate.Controller({"animate_rotation": True})

    def test_ambiguous_native_outputs_are_rejected(self):
        self.assertEqual(rotate.native_output(OUTPUT), ("DSI-1", "normal"))
        with self.assertRaises(ValueError):
            rotate.native_output(OUTPUT + OUTPUT.replace("DSI-1", "DSI-2"))
        with self.assertRaises(ValueError):
            rotate.native_output(OUTPUT.replace("1536x2048", "1920x1080"))

    def test_failed_reconfigure_restores_output_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "rc.xml")
            path.write_bytes(XML)
            calls = []
            failed = False
            def runner(*args):
                nonlocal failed
                calls.append(args)
                if args == ("wlr-randr",):
                    return OUTPUT
                if args == ("labwc", "--reconfigure") and not failed:
                    failed = True
                    raise subprocess.CalledProcessError(1, args)
                return ""
            controller = rotate.Controller({"labwc_config": str(path),
                                            "touch_device": "iPad7,5 Touchscreen"}, runner)
            with self.assertRaises(subprocess.CalledProcessError):
                controller.apply("90")
            self.assertEqual(path.read_bytes(), XML)
            self.assertIn(("wlr-randr", "--output", "DSI-1", "--transform", "normal"), calls)
            self.assertEqual(path.with_name("rc.xml.before-aop-rotation").read_bytes(), XML)

    def test_stale_partial_and_invalid_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "orientation")
            path.write_text("3 1234\n")
            os.utime(path, (100, 100))
            self.assertEqual(rotate.orientation(path, now=102), 3)
            with self.assertRaises(ValueError):
                rotate.orientation(path, now=106)
            for content in ["3", "7 123", "3 -1", "bad 1"]:
                path.write_text(content)
                os.utime(path, (100, 100))
                with self.assertRaises(ValueError):
                    rotate.orientation(path, now=102)

    def test_unlock_reapplies_the_same_sensor_code_after_manual_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config_dir = home / ".config/apple-aop"
            config_dir.mkdir(parents=True)
            state = home / "orientation"
            state.write_text("3 123\n")
            config = config_dir / "rotation.json"
            config.write_text('{"codes":{"3":"90"},"state_file":' +
                              json.dumps(str(state)) + '}')
            lock = config_dir / "rotation.lock"
            clock = [0.0]
            applied = []
            def advance(seconds):
                clock[0] += seconds
                if .7 <= clock[0] < 1.2:
                    lock.touch()
                else:
                    lock.unlink(missing_ok=True)
                if clock[0] >= 2.4:
                    raise SystemExit
            controller = mock.Mock()
            controller.apply.side_effect = applied.append
            with mock.patch.dict(os.environ, {"HOME": directory}), \
                 mock.patch("sys.argv", ["rotate", "--config", str(config)]), \
                 mock.patch.object(rotate, "Controller", return_value=controller), \
                 mock.patch.object(rotate.time, "monotonic", side_effect=lambda: clock[0]), \
                 mock.patch.object(rotate.time, "sleep", side_effect=advance):
                with self.assertRaises(SystemExit):
                    rotate.main()
            self.assertEqual(applied, ["90", "90"])



if __name__ == "__main__":
    unittest.main()
