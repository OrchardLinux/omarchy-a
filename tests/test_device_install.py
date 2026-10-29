"""Run device extraction/promotion with temporary files and no block device."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import orchard_hardware
sys.path.insert(0, str(Path(orchard_hardware.__file__).parent / 'runtime/j71b'))
sys.path.insert(0, str(Path(orchard_hardware.__file__).parent / 'apple'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'image/j71b'))
import device
from test_extraction import stream


class DevicePromotion(unittest.TestCase):
    def exercise(self, *, corrupt=False, existing=True, unexpected_link=False, bad_sudo=False,
                 post_free_bytes=10 * 1024**3, post_free_inodes=100000):
        privileges = {'usr/bin/sudo': {'uid': 0, 'gid': 0, 'mode': 0o4755,
                       'type': 'file', 'sha256': hashlib.sha256(b'executable').hexdigest()}}
        data = stream([
            ('usr/bin/sudo', 'file' if bad_sudo else 'setuid', b'executable'),
            ('usr/libexec/omarchy-desktop-ready', 'file', b'#!/bin/sh\nexit 0\n'),
            ('etc/omarchy/package-privileges.json', 'file', json.dumps(privileges).encode()),
            ('lib', 'symlink', 'usr/lib'),
            ('usr/lib/systemd/systemd', 'file', b'executable'),
            ('usr/libexec/omarchy-diagnostics', 'file', b'executable'),
            ('etc/orchard/release.json', 'file', b'{"release":"1.0"}'),
        ])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, target = root / 'run', root / 'target'
            run.mkdir()
            target.mkdir()
            old = {'release': 'previous'}
            if existing:
                (target / 'chosen').mkdir()
                (target / 'chosen/content').write_text('previous content')
                (target / 'chosen/.orchard-install.json').write_text(json.dumps(old))
            if unexpected_link:
                (target / 'chosen').symlink_to('missing-outside-staging')
            firmware_root = root / 'firmware-source'
            firmware = {'lib/firmware/example/fw.bin': b'firmware',
                        'lib/firmware/example/calibration.txt': b'calibration'}
            for name, content in firmware.items():
                source = firmware_root / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
            (run / 'mixin.json').write_text(json.dumps({'files': {
                name: {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                for name, content in firmware.items()}}))
            sums = root / 'public-sums'
            sums.write_text('')
            spec = {'release': '1.0', 'root': {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                                             'expanded_bytes': 1000, 'compression': 'gzip'}}
            partition = {'id': 'partition', 'filesystem_uuid': 'filesystem', 'path': '/not-a-device'}
            identity = None
            if existing:
                info = (target / 'chosen').stat()
                identity = [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns]
            request = {'directory': 'chosen', 'replace': existing, 'destination_identity': identity, **spec['root']}
            class Input:
                buffer = io.BytesIO(data[:-8] if corrupt else data)
            real_extract = device.extract
            real_verify = device.verify_privileges
            with patch.object(device, 'verify_privileges', side_effect=lambda path: real_verify(path, ownership=False)), \
                 patch.object(device, 'extract', side_effect=lambda *a, **k: real_extract(*a, **k, ownership=False)), \
                 patch.object(device, 'RUN', run), patch.object(device, 'ROOT', target), \
                 patch.object(device, 'PUBLIC_SUMS', sums), \
                 patch.object(device, 'Path', side_effect=lambda value: firmware_root if str(value) == '/' else Path(value)), \
                 patch.object(device, 'config', return_value=spec), \
                 patch.object(device, 'state', return_value={'phase': 'prepare', 'status': 'complete'}), \
                 patch.object(device, 'selected', return_value=partition), \
                 patch.object(device, 'destination', return_value={
                     'exists': existing, 'identity': identity, 'free_bytes': 10 * 1024**3,
                     'reclaimable_bytes': 0, 'inodes_sufficient': True}), \
                 patch.object(device, 'mount_target'), patch.object(device, 'unmount_target'), \
                 patch.object(device.os, 'statvfs', side_effect=lambda _: type('Space', (), {
                     'f_bavail': 10 * 1024**3 if (target / 'chosen').exists() else post_free_bytes,
                     'f_frsize': 1,
                     'f_favail': 100000 if (target / 'chosen').exists() else post_free_inodes})()), \
                 patch.object(device, 'command'), patch.object(device, 'no_faults'), \
                 patch.object(device.sys, 'stdin', Input()), patch.object(device, 'emit'):
                if post_free_bytes < device.capacity_needed(spec['root']) or post_free_inodes < 66560:
                    with self.assertRaisesRegex(ValueError, 'Insufficient space or free inodes after deletion'):
                        device.install(request)
                    self.assertFalse((target / 'chosen').exists())
                    self.assertFalse(list(target.glob('chosen.previous-*')))
                    self.assertEqual(json.loads((run / 'installation.json').read_text())['status'], 'incomplete')
                    self.assertEqual(Input.buffer.tell(), 0)
                elif corrupt:
                    with self.assertRaises((ValueError, EOFError, OSError)):
                        device.install(request)
                    self.assertFalse((target / 'chosen').exists())
                    self.assertEqual(json.loads((run / 'installation.json').read_text())['status'], 'incomplete')
                    self.assertFalse(list(target.glob('chosen.previous-*')))
                elif bad_sudo:
                    with self.assertRaisesRegex(ValueError, 'Privileged package ownership/mode differs'):
                        device.install(request)
                    self.assertFalse((target / 'chosen').exists())
                elif unexpected_link:
                    with self.assertRaisesRegex(ValueError, 'Destination became a symlink'):
                        device.install(request)
                    self.assertTrue((target / 'chosen').is_symlink())
                else:
                    result = device.install(request)
                    self.assertEqual(result['status'], 'complete')
                    marker = json.loads((target / 'chosen/.orchard-install.json').read_text())
                    self.assertEqual(marker['release'], '1.0')
                    self.assertEqual(marker['directory'], 'chosen')
                    for name, content in firmware.items():
                        self.assertEqual((target / 'chosen' / ('usr/' + name)).read_bytes(), content)
                    self.assertEqual((target / 'chosen').stat().st_mode & 0o777, 0o755)
                    self.assertNotIn('previous_directory', marker)
                    self.assertFalse(list(target.glob('chosen.previous-*')))

    def test_post_deletion_capacity_loss_stops_before_reading_archive(self):
        self.exercise(post_free_bytes=0)

    def test_post_deletion_inode_loss_stops_before_reading_archive(self):
        self.exercise(post_free_inodes=0)

    def test_capacity_estimate_includes_overhead_and_margin(self):
        self.assertEqual(device.capacity_needed({'expanded_bytes': 1000}), 1200 + 1024**3)

    def test_destination_reports_data_directory_without_install_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'data'
            target.mkdir()
            (target / 'personal-file').write_bytes(b'keep me')
            partition = {'id': 'partition'}
            with patch.object(device, 'ROOT', root), \
                 patch.object(device, 'selected', return_value=partition), \
                 patch.object(device, 'mount_target'), patch.object(device, 'unmount_target'), \
                 patch.object(device, 'config', return_value={'root': {'expanded_bytes': 1000, 'members': 3}}):
                result = device.destination({'directory': 'data'})
            self.assertTrue(result['exists'])
            self.assertIsNotNone(result['identity'])
            self.assertGreater(result['reclaimable_bytes'], 0)
            self.assertEqual(result['needed_bytes'], 1200 + 1024**3)
            self.assertEqual((target / 'personal-file').read_bytes(), b'keep me')

    def test_directory_usage_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'link').symlink_to('/nonexistent-external-data')
            allocated, inodes = device.directory_usage(root)
            self.assertEqual(inodes, 2)
            self.assertGreaterEqual(allocated, 0)

    def test_cleanup_removes_only_owned_incomplete_staging(self):
        import staging
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partition = {'id': 'partition', 'filesystem_uuid': 'filesystem'}
            receipt = {'release': '1.0', 'sha256': 'a' * 64}
            marker = {'schema': 1, 'profile': 'j71b', 'status': 'incomplete',
                      **partition, 'partition': partition['id'], 'directory': 'chosen',
                      'release': '1.0', 'root_sha256': receipt['sha256']}
            own = root / ('.chosen.install-' + 'a' * 32)
            own.mkdir()
            (own / staging.MARKER).write_text(json.dumps(marker))
            for name in ('chosen', 'chosen.previous-backup', '.unknown.install-' + 'b' * 32):
                (root / name).mkdir()
                (root / name / 'keep').write_text('keep')
            other = root / ('.chosen.install-' + 'c' * 32)
            other.mkdir()
            (other / staging.MARKER).write_text(json.dumps({**marker, 'filesystem_uuid': 'other'}))
            link = root / ('.chosen.install-' + 'd' * 32)
            link.symlink_to(root / 'chosen', target_is_directory=True)
            candidates = staging.scan(root, partition, [receipt], owner_uid=os.getuid())
            self.assertEqual([c['name'] for c in candidates], [own.name])
            staging.remove(root, candidates[0], partition, [receipt], owner_uid=os.getuid())
            self.assertFalse(own.exists())
            self.assertEqual((root / 'chosen/keep').read_text(), 'keep')
            self.assertEqual((root / 'chosen.previous-backup/keep').read_text(), 'keep')
            self.assertTrue(other.exists())
            self.assertTrue(link.is_symlink())

    def test_cleanup_recognizes_legacy_finalization_bug_without_personal_ids(self):
        import staging
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partition = {'id': 'partition', 'filesystem_uuid': 'filesystem'}
            receipt = {'release': '1.0', 'sha256': 'a' * 64}
            own = root / ('.chosen.install-' + 'e' * 32)
            own.mkdir()
            firmware_name = 'lib/firmware/example/calibration.txt'
            marker = {'schema': 1, 'partition': partition['id'], 'filesystem_uuid': partition['filesystem_uuid'],
                      'directory': firmware_name, 'release': '1.0', 'root_sha256': receipt['sha256'], 'completed_at': 1}
            (own / '.orchard-install.json').write_text(json.dumps(marker))
            self.assertEqual(staging.scan(root, partition, [], [firmware_name], os.getuid()), [])
            candidates = staging.scan(root, partition, [receipt], [firmware_name], os.getuid())
            self.assertEqual(len(candidates), 1)
            with self.assertRaisesRegex(ValueError, 'mounted staging'):
                staging.remove(root, candidates[0], partition, [receipt], [firmware_name],
                               mounts=[str(own / 'dev')], owner_uid=os.getuid())
            (own / '.orchard-install.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'changed'):
                staging.remove(root, candidates[0], partition, [receipt], [firmware_name], owner_uid=os.getuid())
            self.assertTrue(own.exists())

    def test_missing_setuid_bit_cannot_promote_a_root(self):
        self.exercise(bad_sudo=True)

    def test_corrupt_stream_cannot_restore_deleted_root(self):
        self.exercise(corrupt=True)

    def test_verified_stream_replaces_without_backup(self):
        self.exercise()

    def test_late_broken_symlink_is_not_overwritten(self):
        self.exercise(existing=False, unexpected_link=True)

    def test_fresh_destination_needs_no_historical_receipt(self):
        self.exercise(existing=False)


if __name__ == '__main__':
    unittest.main()
