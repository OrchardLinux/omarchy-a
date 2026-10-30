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
from release.recovery_audit import read_newc, audit_runtime


def release_files(output):
    """A fake release directory: one root, Pongo, and a recovery and layer per platform."""
    for name in ('rootfs.tar.zst', 'pongo.bin', 'recovery-apple-16k.bin', 'platform-apple-16k.tar.gz',
                 'recovery-apple-4k.bin', 'platform-apple-4k.tar.gz'):
        (output / name).write_bytes(name.encode())
    platforms = {}
    for name, boards in (('apple-16k', ['j71b', 'j71s']), ('apple-4k', ['n61'])):
        layer = manifests.receipt(output / f'platform-{name}.tar.gz')
        layer.update(compression='gzip', expanded_bytes=10, members=2, kernel_release='7.3.0-' + name)
        platforms[name] = {'boards': boards, 'boot': manifests.receipt(output / f'recovery-{name}.bin'),
                           'layer': layer}
    return {'compression': 'zstd', 'expanded_bytes': 100, 'members': 3}, platforms


ORCHARD = {'commit': 'c' * 40, 'modified': False}


class Publication(unittest.TestCase):
    def test_one_manifest_for_every_platform_and_an_index_pinning_its_bytes(self):
        from orchard.manifests import validate
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            root, platforms = release_files(output)
            path = manifests.write(output, 'test-1', root, platforms, ORCHARD)
            doc = manifests.tomllib.loads(path.read_text())
            index = manifests.tomllib.loads((output / 'index.toml').read_text())
            validate(doc), validate(index)
            self.assertEqual(index['release'], manifests.receipt(path))
            self.assertNotIn('device', doc)
            self.assertEqual(doc['platforms'], platforms)
            self.assertEqual(doc['orchard'], ORCHARD)
            self.assertEqual(doc['install']['default_root'], '/omarchy')
            self.assertEqual(doc['root']['sha256'], hashlib.sha256(b'rootfs.tar.zst').hexdigest())
            self.assertEqual(doc['min_orchard'], '0.2.0')
            self.assertEqual(manifests.read_release(path)['platforms'], platforms)
            with self.assertRaises(FileExistsError):
                manifests.write(output, 'test-1', root, platforms, ORCHARD)
            path.write_text(path.read_text() + '# modified\n')
            self.assertNotEqual(index['release']['sha256'], manifests.receipt(path)['sha256'])

    def test_another_distro_is_not_accepted_by_omarchy_auditor_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.toml'
            path.write_text('schema=1\nkind="orchard.install"\ndistro="another"\n')
            with self.assertRaises(ValueError):
                manifests.read_release(path)


class RecoverySealing(unittest.TestCase):
    @staticmethod
    def archive(entries):
        output = io.BytesIO()
        for index, (name, mode, data) in enumerate(entries, 1):
            record(output, index, name, mode, data)
        record(output, len(entries)+1, 'TRAILER!!!', 0, b'')
        output.write(b'\0' * 512)
        return output.getvalue()

    def test_newc_round_trip_and_unsafe_names_duplicates_rejected(self):
        entry = ('init', stat.S_IFREG | 0o755, b'#!/bin/sh\n')
        self.assertEqual(list(read_newc(io.BytesIO(self.archive([entry])))), [entry])
        for entries in ([entry, entry], [('../escape', entry[1], b'bad')], [('/escape', entry[1], b'bad')]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                list(read_newc(io.BytesIO(self.archive(entries))))

    def test_newc_truncation_limits_and_unexpected_trailer_data_rejected(self):
        raw = self.archive([('init', stat.S_IFREG | 0o755, b'#!/bin/sh\n')])
        for bad in (raw[:100], raw[:-1], raw + b'extra', raw[:54] + b'ffffffff' + raw[62:]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                list(read_newc(io.BytesIO(bad)))

    def exercise(self, *, different_kernel=False, private_file=None, corrupt_public=False):
        kernel_release = '7.3.0-test'
        files = {name: b'executable' for name in (
            'init', 'usr/bin/orchard-device', 'usr/bin/python3', 'sbin/capture-adt',
            'sbin/authorize-key', 'sbin/recovery-start-ssh', 'usr/sbin/blkid', 'usr/sbin/sfdisk',
            'usr/sbin/mke2fs', 'etc/mke2fs.conf')}
        for name in ('device.py', 'identity.py', 'storage-fence', 'adt.py'):
            files['usr/libexec/orchard/' + name] = b'# runtime\n'
        config = {'release': 'test-1', 'protocol': 1,
                  'kernel_release': '7.3.0-other' if different_kernel else kernel_release}
        files['etc/orchard/release.json'] = json.dumps(config).encode()
        public = ''.join(hashlib.sha256(data).hexdigest() + '  /' + name + '\n' for name, data in sorted(files.items()))
        if corrupt_public:
            public = '0' * 64 + public[64:]
        files['etc/orchard/public.SHA256SUMS'] = public.encode()
        if private_file:
            files[private_file] = b'not public'
        entries = [(name, stat.S_IFREG | 0o755, data) for name, data in sorted(files.items())]
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'recovery.bin'
            image.write_bytes(gzip.compress(self.archive(entries)))
            Path(str(image) + '.json').write_text(json.dumps({'components': [
                {'name': 'initramfs', 'offset': 0, 'bytes': image.stat().st_size}]}))
            from release.audit import private_firmware
            return audit_runtime(image, kernel_release, 'test-1', private_firmware())

    def test_actual_recovery_root_lock_and_public_hashes_are_checked(self):
        self.assertGreater(self.exercise()['members'], 0)
        for arguments in ({'different_kernel': True}, {'corrupt_public': True}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.exercise(**arguments)

    def test_public_recovery_cannot_contain_firmware_or_session_credentials(self):
        # Any described board's private firmware, not only one board's.
        recipe = json.loads(firmware_path('n61').read_text())
        for name in (recipe['outputs'][0]['destination'], 'run/recovery/ssh_host_ed25519_key'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.exercise(private_file=name)


if __name__ == '__main__':
    unittest.main()


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
