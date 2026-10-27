"""Hosted metadata binds immutable artifact URLs to the local release bytes."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from release import manifests
from release.merge import merge
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

    def test_merged_devices_publish_one_shared_pongo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.bundle(root / 'local')
            (root / 'j71t').mkdir()
            for name in ('j71t-rootfs.tar.zst', 'j71t-recovery.bin', 'pongo.bin'):
                (root / 'j71t' / name).write_bytes(name.encode())
            manifests.write(root / 'j71t', 'test-1', {'compression': 'zstd', 'expanded_bytes': 100, 'members': 3},
                            device='j71t')
            merge(root / 'local', [root / 'j71t'])
            path = publish(root / 'local', 'v1.2.3', root / 'public')
            index = manifests.tomllib.loads(path.read_text())
            self.assertEqual(sorted(index['devices']), ['j71b', 'j71t'])
            doc = manifests.tomllib.loads((root / 'public/j71t-checkm8-pongo.toml').read_text())
            self.assertEqual(doc['device'], 'j71t')
            self.assertTrue(doc['boot']['url'].endswith('/v1.2.3/j71t-recovery.bin'))
            self.assertTrue(doc['pongo']['url'].endswith('/v1.2.3/pongo.bin'))
            self.assertEqual(sorted(p.name for p in (root / 'public').iterdir()), [
                'index.toml', 'j71b-checkm8-pongo.toml', 'j71t-checkm8-pongo.toml', 'j71t-recovery.bin',
                'j71t-rootfs.tar.zst', 'pongo.bin', 'recovery.bin', 'rootfs.tar.zst'])


if __name__ == '__main__':
    unittest.main()
