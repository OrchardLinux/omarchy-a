"""Hosted metadata binds immutable artifact URLs to the local release bytes."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from release import manifests
from release.publish import publish


class HostedPublication(unittest.TestCase):
    def bundle(self, root):
        root.mkdir()
        for name in ('rootfs.tar.zst', 'recovery.bin', 'pongo.bin'):
            (root / name).write_bytes(name.encode())
        manifests.write(root, 'test-1', {'compression': 'zstd', 'expanded_bytes': 100, 'members': 3})

    def test_hosted_index_pins_rewritten_manifest_and_immutable_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.bundle(root / 'local')
            original = (root / 'local/index.toml').read_bytes()
            output = root / 'public'
            path = publish(root / 'local', 'v1.2.3', output)
            index = manifests.tomllib.loads(path.read_text())
            pin = index['devices']['j71b']['checkm8-pongo']
            manifest = output / 'j71b-checkm8-pongo.toml'
            self.assertEqual(pin['sha256'], hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(pin['bytes'], manifest.stat().st_size)
            self.assertNotIn('file', pin)
            doc = manifests.tomllib.loads(manifest.read_text())
            for role in ('root', 'boot', 'pongo'):
                self.assertNotIn('file', doc[role])
                self.assertIn('/releases/download/v1.2.3/', doc[role]['url'])
            self.assertEqual((root / 'local/index.toml').read_bytes(), original)
            self.assertEqual((output / 'rootfs.tar.zst').read_bytes(), b'rootfs.tar.zst')
            with self.assertRaises(FileExistsError):
                publish(root / 'local', 'v1.2.3', output)

    def test_corrupt_asset_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.bundle(root / 'local')
            (root / 'local/recovery.bin').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                publish(root / 'local', 'v1', root / 'public')
            self.assertFalse((root / 'public').exists())


if __name__ == '__main__':
    unittest.main()
