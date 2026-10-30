"""Synthetic fixtures only: never embed Apple images or per-device identity."""
import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "desktop/aop/firmware.py"
spec = importlib.util.spec_from_file_location("aop_firmware", SOURCE)
firmware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firmware)


def scalar(kind, data):
    return struct.pack("<I", kind << 24 | len(data)) + data + bytes((-len(data)) % 4)


class AopFirmwareTests(unittest.TestCase):
    def test_container_data_and_object_references(self):
        data = (b"\xd3\0\0\0" + struct.pack("<I", 0x01000001) + scalar(8, b"images\0") +
                struct.pack("<I", 0x02000002) + scalar(10, b"synthetic") + struct.pack("<I", 0x8c000003))
        self.assertEqual(firmware.unserialize(data), {"images": [b"synthetic", b"synthetic"]})

    def test_truncation_references_and_limits(self):
        for bad in (b"", b"\xd3\0\0\0", b"\xd3\0\0\0" + struct.pack("<I", 0x0c000000),
                    b"\xd3\0\0\0" + struct.pack("<I", 0x02ffffff),
                    b"\xd3\0\0\0" + scalar(10, b"test") + b"trailer"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                firmware.unserialize(bad)

    def test_unknown_firmware_rejected_before_parsing(self):
        with mock.patch.object(firmware, "unserialize") as parser:
            with self.assertRaises(ValueError):
                firmware.images(b"synthetic firmware")
            parser.assert_not_called()

    def test_image_roles_sizes_and_hashes_are_checked(self):
        image = b"synthetic firmware"
        document = {"firmware": [{"data": image, "header": {"coprocessor": "test"}}]}
        expected = (("test", len(image), hashlib.sha256(image).hexdigest()),)
        with mock.patch.object(firmware, "CONTAINER_SHA256", hashlib.sha256(b"container").hexdigest()), \
             mock.patch.object(firmware, "IMAGES", expected), \
             mock.patch.object(firmware, "unserialize", return_value=document):
            self.assertEqual(firmware.images(b"container"), [image])
            document["firmware"][0]["data"] = b"corrupt firmware!"
            with self.assertRaises(ValueError):
                firmware.images(b"container")


if __name__ == "__main__":
    unittest.main()
