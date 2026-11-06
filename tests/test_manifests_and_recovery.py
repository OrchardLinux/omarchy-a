"""New publication/sealing checks; no kernel execution or physical devices."""
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
import unittest

from orchard.hardware import firmware_path
from orchard.image.initramfs import record
from release import manifests


def release_files(output):
    """A fake release directory: the root image, its logo, and what orchard offers."""
    for name in ('root.blocks.zst', 'root.map.json', 'logo.bin', 'pongo.bin', 'm1n1.bin', 'install-tools.tar.gz',
                 'platform-apple-16k.tar.gz', 'platform-apple-4k.tar.gz'):
        (output / name).write_bytes(name.encode())
    platforms = {}
    for name, boards in (('apple-16k', ['j71b', 'j71s']), ('apple-4k', ['n61'])):
        platforms[name] = {**manifests.receipt(output / f'platform-{name}.tar.gz'), 'compression': 'gzip',
                           'expanded_bytes': 10, 'members': 2, 'kernel_release': '7.3.0-' + name, 'boards': boards}
    root = {**manifests.receipt(output / 'root.blocks.zst'), 'compression': 'zstd', 'format': 'blocks',
            'expanded_bytes': 100, 'members': 3, 'map': manifests.receipt(output / 'root.map.json')}
    offered = {'loaders': {'pongo': manifests.receipt(output / 'pongo.bin'), 'm1n1': manifests.receipt(output / 'm1n1.bin')},
               'install_tools': manifests.receipt(output / 'install-tools.tar.gz'), 'platforms': platforms}
    return root, offered


ORCHARD = {'commit': 'c' * 40, 'modified': False}


class Publication(unittest.TestCase):
    def test_one_manifest_for_every_platform_and_an_index_pinning_its_bytes(self):
        from orchard.manifests import validate
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            root, offered = release_files(output)
            path = manifests.write(output, 'test-1', root, offered, ORCHARD)
            doc = manifests.tomllib.loads(path.read_text())
            index = manifests.tomllib.loads((output / 'index.toml').read_text())
            validate(doc), validate(index)
            self.assertEqual(index['release'], manifests.receipt(path))
            self.assertNotIn('device', doc)
            self.assertEqual(doc['root'], root)
            self.assertEqual(doc['m1n1'], offered['loaders']['m1n1'])
            self.assertEqual(sorted(doc['platforms']), ['apple-16k', 'apple-4k'])
            self.assertEqual(doc['platforms']['apple-4k']['boards'], ['n61'])
            self.assertNotIn('boards', doc['platforms']['apple-4k']['layer'])
            self.assertNotIn('boot', doc['platforms']['apple-4k'])
            self.assertEqual(doc['orchard'], ORCHARD)
            self.assertEqual(doc['install'], {'default_root': '/omarchy', 'ready': '/run/omarchy-greeter/ready.json', 'account': {
                'user': 'tablet', 'password': True, 'pin': True, 'passwordless_sudo': False}})
            self.assertEqual(doc['root']['sha256'], hashlib.sha256(b'root.blocks.zst').hexdigest())
            self.assertEqual(doc['min_orchard'], '0.2.0')
            self.assertEqual(manifests.read_release(path)['platforms'], doc['platforms'])
            with self.assertRaises(FileExistsError):
                manifests.write(output, 'test-1', root, offered, ORCHARD)
            path.write_text(path.read_text() + '# modified\n')
            self.assertNotEqual(index['release']['sha256'], manifests.receipt(path)['sha256'])

    def test_another_distro_is_not_accepted_by_omarchy_auditor_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.toml'
            path.write_text('schema=1\nkind="orchard.install"\ndistro="another"\n')
            with self.assertRaises(ValueError):
                manifests.read_release(path)


class LayerAudit(unittest.TestCase):
    """The release audit reads orchard's platform layer as the installer will write it."""
    def layer(self, directory, **change):
        from orchard.image import platform
        release = '7.3.0-test'
        files = {f'usr/lib/modules/{release}/vmlinuz': (b'kernel', 0o644),
                 f'usr/lib/modules/{release}/kernel/x.ko': (b'module', 0o644),
                 'usr/lib/orchard/platform.json': (json.dumps({
                     'schema': 1, 'platform': change.get('platform', 'apple-16k'), 'kernel_release': release,
                     'boards': {'j71b': 't8010-j71b'}}).encode(), 0o644)}
        files.update(change.get('extra', {}))
        sums = ''.join(hashlib.sha256(data).hexdigest() + '  /' + name + '\n' for name, (data, _) in sorted(files.items()))
        files['usr/lib/orchard/platform.SHA256SUMS'] = (sums.encode(), 0o644)
        path = Path(directory) / 'platform-apple-16k.tar.gz'
        path.unlink(missing_ok=True)
        expanded, members = platform.write(files, path)
        return path, {'expanded_bytes': expanded, 'members': members, 'kernel_release': release}

    def test_a_layer_is_checked_against_its_receipt_and_its_platform(self):
        from release.audit import audit_layer
        with tempfile.TemporaryDirectory() as directory:
            result = audit_layer(*self.layer(directory)[:1], 'apple-16k', self.layer(directory)[1], set())
            self.assertEqual(result['boards'], {'j71b': 't8010-j71b'})
            path, row = self.layer(directory, platform='apple-4k')
            with self.assertRaisesRegex(ValueError, 'another platform'):
                audit_layer(path, 'apple-16k', row, set())
            path, row = self.layer(directory)
            with self.assertRaisesRegex(ValueError, 'differs from its receipt'):
                audit_layer(path, 'apple-16k', {**row, 'members': 1}, set())
            private = json.loads(firmware_path('j71b').read_text())['outputs'][0]['destination']
            path, row = self.layer(directory, extra={'usr/' + private: (b'secret', 0o644)})
            with self.assertRaisesRegex(ValueError, 'Private firmware'):
                audit_layer(path, 'apple-16k', row, {private})
