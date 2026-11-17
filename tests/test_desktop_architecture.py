"""The builder the image's omarchy-a package is made in."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'desktop'))
from target import builder


def elf(architecture):
    data = bytearray(64)
    data[:7] = b'\x7fELF' + bytes((1 if architecture == 'armv7h' else 2, 1, 1))
    struct.pack_into('<HHI', data, 16, 3, 40 if architecture == 'armv7h' else 183, 1)
    struct.pack_into('<H', data, 40 if architecture == 'armv7h' else 52, 52 if architecture == 'armv7h' else 64)
    if architecture == 'armv7h':
        struct.pack_into('<I', data, 36, 0x05000400)
    return bytes(data)


class FakeBuildenv:
    def __init__(self, native=False):
        self.is_native = native
        self.calls = []

    def native(self):
        return self.is_native

    def build(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class DesktopArchitecture(unittest.TestCase):
    def test_native_builder_rejects_wrong_machine(self):
        with patch('target.platform.machine', return_value='aarch64'):
            with self.assertRaisesRegex(ValueError, 'architecture differs'):
                builder(FakeBuildenv(True), 'armv7h')

    def test_armv7_container_requires_an_explicit_target_builder(self):
        environment = FakeBuildenv()
        with self.assertRaisesRegex(ValueError, '--builder-image'):
            builder(environment, 'armv7h')
        self.assertEqual(environment.calls, [])
        self.assertEqual(builder(environment, 'armv7h', 'compiler:armv7'), 'compiler:armv7')
        self.assertEqual(environment.calls, [])

    def test_default_aarch64_builder_keeps_pinned_recipe(self):
        environment = FakeBuildenv()
        self.assertEqual(builder(environment, 'aarch64'), 'localhost/omarchy-a-desktop-builder:arm64')
        self.assertEqual(environment.calls[0][1], {'arch': 'arm64'})
        self.assertEqual(environment.calls[0][0][1], PROJECT / 'desktop/Containerfile')


if __name__ == '__main__':
    unittest.main()
