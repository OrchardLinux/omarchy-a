"""Release boundaries reject a desktop component or root of another architecture."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from release import manifests, public_root


def elf(architecture):
    arm = architecture == 'armv7h'
    raw = bytearray(52 if arm else 64)
    raw[:7] = b'\x7fELF' + bytes((1 if arm else 2, 1, 1))
    struct.pack_into('<HHI', raw, 16, 2, 40 if arm else 183, 1)
    struct.pack_into('<H', raw, 40 if arm else 52, len(raw))
    if arm:
        struct.pack_into('<I', raw, 36, 0x05000400)
    return bytes(raw)


class ReleaseArchitecture(unittest.TestCase):
    def test_access_tools_must_match_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = {}
            for name in ('busybox', 'dropbear', 'dropbearkey'):
                path = root / name
                path.write_bytes(elf('armv7h'))
                tools[name] = path
            self.assertEqual(len(public_root.access_files(tools, 'armv7h')), 3)
            tools['dropbear'].write_bytes(elf('aarch64'))
            with self.assertRaisesRegex(ValueError, 'dropbear'):
                public_root.access_files(tools, 'armv7h')

    def test_base_receipt_refuses_foreign_root_before_assembly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / 'base.json'
            receipt.write_text(json.dumps({'architecture': 'aarch64'}))
            with self.assertRaisesRegex(ValueError, 'Base root architecture'):
                public_root.build(root / 'base.gz', receipt, root / 'out', 'test', architecture='armv7h')
            self.assertFalse((root / 'out').exists())

    def test_armv7_manifest_names_the_32_bit_loaders_without_pongo(self):
        from test_release_contracts import armv7_files
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            block, offered = armv7_files(root)
            path = manifests.write(root, 'armv7-test', block, offered, {'commit': 'a' * 40, 'modified': False},
                                   architecture='armv7h')
            record = manifests.read_release(path)
            self.assertEqual(record['boot_method'], 'recovery-autogo')
            self.assertEqual(sorted(record['loaders']), ['cascadia p105'])
            self.assertIsNone(record['pongo'])
            self.assertIsNone(record['logo'])


if __name__ == '__main__':
    unittest.main()
