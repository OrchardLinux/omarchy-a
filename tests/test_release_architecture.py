"""Release boundaries reject a desktop component or root of another architecture."""
import hashlib
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
    def cursor(self, root, binary_architecture, receipt_architecture):
        contents = {'wtype': elf(binary_architecture), 'LICENSE': b'MIT'}
        for name, data in contents.items():
            (root / name).write_bytes(data)
        pin = json.loads((public_root.PROJECT / 'desktop/cursor/wtype.json').read_text())
        record = {'schema': 1, 'architecture': receipt_architecture, 'source': pin,
                  'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
        (root / 'manifest.json').write_text(json.dumps(record))

    def test_correct_hash_cannot_disguise_wrong_isa_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.cursor(root, 'armv7h', 'armv7h')
            self.assertEqual(public_root.cursor_files(root, 'armv7h')['usr/libexec/omarchy-wtype'][0],
                             elf('armv7h'))
            self.cursor(root, 'aarch64', 'armv7h')
            with self.assertRaisesRegex(ValueError, 'ELF|architecture'):
                public_root.cursor_files(root, 'armv7h')
            self.cursor(root, 'armv7h', 'aarch64')
            with self.assertRaisesRegex(ValueError, 'receipt'):
                public_root.cursor_files(root, 'armv7h')

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

    def test_legacy_labwc_receipt_still_rejects_foreign_isa(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ('labwc', 'LICENSE', 'source.tar.gz', '0001-cancel-super-tap-on-pointer.patch',
                     '0002-bottom-edge-swipe.patch', '0003-session-transitions.patch',
                     'packages.lock', 'compiler.txt', 'version.txt')
            contents = {name: elf('armv7h') if name == 'labwc' else b'fixture' for name in names}
            for name, data in contents.items():
                (root / name).write_bytes(data)
            pin = json.loads((public_root.PROJECT / 'desktop/labwc/source.json').read_text())
            record = {'schema': 1, 'source': pin,
                      'files': {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
            (root / 'manifest.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'Labwc.*ELF|architecture'):
                public_root.labwc_files(root, 'aarch64')

    def test_base_receipt_refuses_foreign_root_before_assembly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / 'base.json'
            receipt.write_text(json.dumps({'architecture': 'aarch64'}))
            with self.assertRaisesRegex(ValueError, 'Base root architecture'):
                public_root.build(root / 'base.gz', receipt, root / 'out', 'test', root,
                                  architecture='armv7h')
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
