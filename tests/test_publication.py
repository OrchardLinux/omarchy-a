"""Hosted metadata binds immutable artifact URLs to the local release bytes."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from release import manifests
from release.publish import publish
from test_manifests_and_recovery import ORCHARD, release_files


class HostedPublication(unittest.TestCase):
    def bundle(self, root):
        root.mkdir()
        manifests.write(root, 'test-1', *release_files(root), ORCHARD)

    def test_hosted_index_pins_rewritten_manifest_and_immutable_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.bundle(root / 'local')
            original = (root / 'local/index.toml').read_bytes()
            output = root / 'public'
            path = publish(root / 'local', 'v1.2.3', output)
            index = manifests.tomllib.loads(path.read_text())
            pin = index['release']
            manifest = output / 'release.toml'
            self.assertEqual(pin['sha256'], hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(pin['bytes'], manifest.stat().st_size)
            self.assertNotIn('file', pin)
            doc = manifests.tomllib.loads(manifest.read_text())
            receipts = [doc['root'], doc['pongo']]
            receipts += [files[role] for files in doc['platforms'].values() for role in ('boot', 'layer')]
            self.assertEqual(len(receipts), 6)
            for receipt in receipts:
                self.assertNotIn('file', receipt)
                self.assertIn('/releases/download/v1.2.3/', receipt['url'])
            self.assertEqual(doc['platforms']['apple-4k']['boards'], ['n61'])
            self.assertEqual((root / 'local/index.toml').read_bytes(), original)
            self.assertEqual((output / 'rootfs.tar.zst').read_bytes(), b'rootfs.tar.zst')
            with self.assertRaises(FileExistsError):
                publish(root / 'local', 'v1.2.3', output)

    def test_corrupt_asset_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.bundle(root / 'local')
            (root / 'local/platform-apple-4k.tar.gz').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                publish(root / 'local', 'v1', root / 'public')
            self.assertFalse((root / 'public').exists())


if __name__ == '__main__':
    unittest.main()
