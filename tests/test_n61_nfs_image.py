"""N61 artifact/ABI binding and private NFS staging, using tiny local fixtures."""
from contextlib import ExitStack, redirect_stdout
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import uuid

from orchard_cli import firmware

from release.n61 import audit, build, prepare_nfs
from release.n61.common import KERNEL_RELEASE, PROJECT, encoded, member_record, sha


def elf():
    data = bytearray(64)
    data[:6] = b'\x7fELF\x02\x01'
    data[18:20] = b'\xb7\x00'
    return bytes(data)


class N61ImageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = self.root / 'base'
        self.base.mkdir()
        sudo = b'sudo fixture\n'
        brightness = 'home/tablet/.local/share/omarchy-ipad/bin/omarchy-brightness-display'
        old_brightness = b'old brightness helper\n'
        mtree = ('./usr/bin/sudo type=file uid=0 gid=0 mode=4755 size=%d sha256digest=%s\n'
                 './var/log/journal type=dir uid=0 gid=190 mode=2755\n') % (len(sudo), hashlib.sha256(sudo).hexdigest())
        files = {
            'usr/lib/systemd/systemd': (elf(), 0o755),
            'usr/bin/sudo': (sudo, 0o4755),
            'usr/local/libexec/arch-ipad-login-session': ((PROJECT / 'desktop/configuration/login-session').read_bytes(), 0o755),
            'home/tablet/.config/labwc/autostart': ((PROJECT / 'desktop/configuration/labwc-autostart').read_bytes(), 0o755),
            'home/tablet/.local/share/omarchy-ipad/shell/shell.qml': (b'// shell fixture\n', 0o644),
            brightness: (old_brightness, 0o755),
            'arch-ipad-ui-manifest.json': (encoded({brightness: hashlib.sha256(old_brightness).hexdigest()}), 0o644),
            'var/lib/pacman/local/sudo-1/mtree': (mtree.encode(), 0o644),
        }
        directories = {'dev', 'proc', 'sys', 'run', 'etc', 'var/log/journal'}
        for key in files:
            directories.update(str(p) for p in Path(key).parents if str(p) != '.')
        archive = self.base / 'rootfs.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            for key in sorted(directories):
                member = tarfile.TarInfo(key)
                member.type, member.mode = tarfile.DIRTYPE, 0o755
                if key == 'var/log/journal':
                    member.mode, member.gid = 0o2755, 190
                stream.addfile(member)
            for key, (data, mode) in files.items():
                member = tarfile.TarInfo(key)
                member.mode, member.size = mode, len(data)
                stream.addfile(member, io.BytesIO(data))
            member = tarfile.TarInfo('lib')
            member.type, member.linkname = tarfile.SYMTYPE, '/usr/lib'
            stream.addfile(member)
        (self.base / 'packages.lock').write_text('sudo 1\nlabwc 0.20\n')
        self.receipt = {'kind': 'omarchy-a.base', 'profile': 'n61', 'architecture': 'aarch64',
                        'release': 'n61-fixture', 'bytes': archive.stat().st_size, 'sha256': sha(archive),
                        'packages_lock_sha256': sha(self.base / 'packages.lock')}
        (self.base / 'rootfs.tar.gz.json').write_bytes(encoded(self.receipt))
        self.kernel = self.root / 'kernel'
        modules = self.kernel / 'lib/modules' / KERNEL_RELEASE
        modules.mkdir(parents=True)
        (self.kernel / 'kernel.release').write_text(KERNEL_RELEASE + '\n')
        (modules / 'modules.dep').write_text('fixture.ko:\n')
        (modules / 'fixture.ko').write_bytes(elf() + b'vermagic=' + KERNEL_RELEASE.encode() + b' SMP\n')
        (self.kernel / 'Image.gz').write_bytes(b'kernel fixture')
        (self.kernel / 'dtbs').mkdir()
        (self.kernel / 'n61.dtb').write_bytes(b'n61 device tree fixture')
        (self.kernel / 'dtbs/t7000-n61.dtb').write_bytes(b'n61 device tree fixture')
        kernel_files = {}
        for path in self.kernel.rglob('*'):
            if path.is_file():
                kernel_files[path.relative_to(self.kernel).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        self.hardware = self.root / 'hardware'
        self.hardware.mkdir()
        (self.hardware / '__init__.py').write_text('')
        recipe_files = {}
        for key in ('devices/n61/device.toml', 'devices/n61/firmware.json', 'kernel/configs/apple-4k/config'):
            path = self.hardware / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture recipe')
            recipe_files[key] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        recipe_sha = hashlib.sha256(json.dumps(recipe_files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.kernel_receipt = {'schema': 1, 'device': 'n61', 'platform': 'apple-4k', 'dtb': 't7000-n61',
                               'kernel_release': KERNEL_RELEASE, 'source': {
                                   'commit': '1' * 40, 'tree': '2' * 40, 'prepared_tree': '3' * 40,
                                   'patch_list_sha256': '4' * 64, 'config_sha256': '5' * 64},
                               'hardware_recipe': {'sha256': recipe_sha, 'files': recipe_files},
                               'files': kernel_files}
        (self.kernel / 'receipt.json').write_bytes(encoded(self.kernel_receipt))
        self.modules = modules.parent
        self.components = ExitStack()
        self.addCleanup(self.components.close)
        self.components.enter_context(patch.object(build.desktop, 'cursor_files', return_value={'usr/libexec/omarchy-wtype': (elf(), 0o755)}))
        self.components.enter_context(patch.object(build.desktop, 'bluetooth_files', return_value={}))
        self.components.enter_context(patch.object(build.desktop, 'labwc_files', return_value={'usr/bin/labwc': (elf(), 0o755)}))

    def compose(self):
        output = self.root / 'release'
        result = build.build(self.base, self.modules, Path('/cursor'), Path('/bluetooth'), Path('/labwc'), output,
                             hardware=self.hardware)
        return output, result

    def firmware_mixin(self, *, profile='n61', data=b'N61 firmware fixture\n'):
        destination = 'lib/firmware/apple/n61-fwstart.z2fw'
        prepared = self.root / 'mixin-source'
        path = prepared / 'firmware' / destination
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        output = self.root / 'private-mixin'
        output.mkdir()
        metadata = {'schema': 1, 'profile': profile,
                    'files': {destination: {'bytes': len(data), 'sha256': sha(path)}}}
        mixin, _ = firmware.pack_mixin(prepared, metadata, output)
        expected = {'outputs': [{'destination': destination, 'sha256': sha(path)}]}
        return mixin, output / 'mixin.json', expected

    def test_native_root_keeps_matching_modules_and_software_desktop_policy(self):
        output, result = self.compose()
        self.assertEqual(audit.audit(output), result)
        self.assertEqual(result['kernel']['receipt_sha256'], sha(self.kernel / 'receipt.json'))
        self.assertEqual(json.loads((output / 'kernel.json').read_text()), self.kernel_receipt)
        self.assertEqual(result['desktop']['scale'], 1.5)
        catalog = json.loads((output / 'rootfs.catalog.json').read_text())
        self.assertIn('usr/lib/modules/' + KERNEL_RELEASE + '/fixture.ko', catalog)
        self.assertEqual(catalog['usr/bin/sudo']['mode'], 0o4755)
        self.assertEqual(catalog['var/log/journal']['mode'], 0o2755)
        self.assertEqual(catalog['etc/sudoers.d/90-tablet-passwordless']['mode'], 0o440)
        self.assertNotIn('etc/orchard/nfs-root.json', catalog)
        self.assertFalse(any('orchard-j71b' in key for key in catalog))
        self.assertIn('usr/lib/systemd/system/omarchy-zram.service', catalog)
        for key in ('usr/libexec/omarchy-screen-toggle',
                    'usr/lib/systemd/system/omarchy-pacman-init.service'):
            source = PROJECT / 'system/j71b/overlay' / key
            self.assertEqual(catalog[key]['sha256'], sha(source))
        self.assertEqual(catalog['usr/libexec/omarchy-screen-toggle']['mode'], 0o755)
        backlight_rule = 'usr/lib/udev/rules.d/70-n61-backlight.rules'
        self.assertEqual(catalog[backlight_rule]['sha256'], sha(PROJECT / 'system/n61/overlay' / backlight_rule))
        self.assertIn('KERNEL=="20e200010.backlight"',
                      (PROJECT / 'system/n61/overlay' / backlight_rule).read_text())
        brightness = 'home/tablet/.local/share/omarchy-ipad/bin/omarchy-brightness-display'
        self.assertEqual(catalog[brightness]['sha256'], sha(PROJECT / 'desktop/shell/bin/omarchy-brightness-display'))
        self.assertEqual((catalog[brightness]['uid'], catalog[brightness]['gid'], catalog[brightness]['mode']),
                         (1000, 1000, 0o755))
        self.assertEqual(
            catalog['etc/systemd/system/multi-user.target.wants/omarchy-pacman-init.service']['target'],
            '/usr/lib/systemd/system/omarchy-pacman-init.service')

    def test_wrong_base_architecture_and_module_release_stop_before_output(self):
        receipt = dict(self.receipt, architecture='armv7h')
        (self.base / 'rootfs.tar.gz.json').write_bytes(encoded(receipt))
        with self.assertRaisesRegex(ValueError, 'AArch64 base'):
            self.compose()
        (self.base / 'rootfs.tar.gz.json').write_bytes(encoded(self.receipt))
        (self.kernel / 'kernel.release').write_text('wrong-kernel\n')
        with self.assertRaisesRegex(ValueError, '4K kernel module'):
            self.compose()
        self.assertFalse((self.root / 'release').exists())

    def test_changed_image_or_receipt_is_rejected(self):
        output, _ = self.compose()
        path = output / 'rootfs.json'
        receipt = json.loads(path.read_text())
        receipt['kernel_release'] = 'wrong-kernel'
        path.write_bytes(encoded(receipt))
        with self.assertRaisesRegex(ValueError, 'NFS root contract'):
            audit.audit(output)
        receipt['kernel_release'] = KERNEL_RELEASE
        path.write_bytes(encoded(receipt))
        with (output / 'rootfs.tar.gz').open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'root stream differs'):
            audit.audit(output)

    def test_kernel_component_rejects_mismatched_image_module_and_identity(self):
        for relative in ('Image.gz', 'lib/modules/' + KERNEL_RELEASE + '/fixture.ko'):
            path = self.kernel / relative
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'kernel component differs'):
                self.compose()
            self.assertFalse((self.root / 'release').exists())
            path.write_bytes(original)
        changed = dict(self.kernel_receipt, device='j71b')
        (self.kernel / 'receipt.json').write_bytes(encoded(changed))
        with self.assertRaisesRegex(ValueError, 'component identity'):
            self.compose()
        self.assertFalse((self.root / 'release').exists())

    def test_hardware_snapshot_and_release_name_are_bound_to_output(self):
        changed = self.hardware / 'devices/n61/firmware.json'
        changed.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Hardware package differs'):
            self.compose()
        changed.write_bytes(b'fixture recipe')
        output = self.root / 'named-release'
        result = build.build(self.base, self.modules, Path('/cursor'), Path('/bluetooth'), Path('/labwc'), output,
                             release='n61-20261029.1', hardware=self.hardware)
        self.assertEqual(result['release'], 'n61-20261029.1')
        self.assertEqual(result['base_release'], 'n61-fixture')
        self.assertEqual(result['producer']['hardware']['kind'], 'installed')
        self.assertEqual(audit.audit(output), result)

    def test_private_staging_mints_exact_root_binding_and_preserves_guest_links(self):
        output, receipt = self.compose()
        destination = self.root / 'private-root'
        with patch.object(prepare_nfs.os, 'geteuid', return_value=0), \
                patch.object(prepare_nfs.os, 'chown'), patch.object(prepare_nfs.os, 'lchown'), \
                patch.object(prepare_nfs.os, 'fchown'), \
                patch.object(prepare_nfs.os, 'fchmod', wraps=os.fchmod) as chmod, \
                patch.object(prepare_nfs, 'verify_privileges'), \
                patch.object(prepare_nfs, 'require_case_sensitive'), redirect_stdout(io.StringIO()):
            staged = prepare_nfs.prepare(output, destination)
        marker = destination / 'etc/orchard/nfs-root.json'
        identity = json.loads(marker.read_text())
        self.assertEqual(identity['kind'], 'orchard.nfs-root')
        self.assertEqual(identity['architecture'], 'aarch64')
        self.assertEqual(identity['root_id'], str(uuid.UUID(identity['root_id'])))
        self.assertEqual(identity['image_sha256'], receipt['root']['sha256'])
        self.assertEqual(identity['image_receipt_sha256'], sha(output / 'rootfs.json'))
        self.assertEqual((destination / 'etc/hostname').read_text(), 'omarchy-n61\n')
        self.assertIn('127.0.1.1 omarchy-n61\n', (destination / 'etc/hosts').read_text())
        self.assertEqual(staged['root_identity_sha256'], sha(marker))
        self.assertEqual(os.readlink(destination / 'lib'), 'usr/lib')
        self.assertIn(0o4755, [call.args[1] for call in chmod.call_args_list])
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((destination.parent / 'private-root.private.json').stat().st_mode), 0o600)

    def test_archive_link_escape_is_rejected(self):
        member = tarfile.TarInfo('usr/link')
        member.type, member.linkname = tarfile.SYMTYPE, '../../outside'
        with self.assertRaisesRegex(ValueError, 'escapes'):
            member_record(member)

    def test_native_private_firmware_is_root_owned_and_bound_to_staging_receipt(self):
        output, public = self.compose()
        mixin, receipt, expected = self.firmware_mixin()
        destination = self.root / 'firmware-root'
        with patch.object(prepare_nfs.os, 'geteuid', return_value=0), \
                patch.object(prepare_nfs.os, 'chown'), patch.object(prepare_nfs.os, 'lchown'), \
                patch.object(prepare_nfs.os, 'fchown') as chown, \
                patch.object(prepare_nfs, 'verify_privileges'), \
                patch.object(prepare_nfs, 'require_case_sensitive'), \
                patch.object(prepare_nfs.firmware, 'recipe_for', return_value=expected) as recipe, \
                patch.object(prepare_nfs.firmware, 'ensure', side_effect=AssertionError('firmware acquisition')), \
                redirect_stdout(io.StringIO()):
            result = prepare_nfs.prepare(output, destination, firmware_mixin=mixin, firmware_receipt=receipt)
        recipe.assert_called_once_with('n61')
        key = expected['outputs'][0]['destination']
        staged = destination / ('usr/' + key)
        self.assertEqual(sha(staged), expected['outputs'][0]['sha256'])
        self.assertEqual((destination / key).read_bytes(), staged.read_bytes())
        self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o600)
        self.assertEqual(chown.call_args.args[1:], (0, 0))
        self.assertEqual(result['firmware_mixin']['sha256'], sha(mixin))
        self.assertEqual(result['firmware_mixin']['files'][key]['sha256'], sha(staged))
        self.assertEqual(audit.audit(output), public)
        self.assertNotIn(key, json.loads((output / 'rootfs.catalog.json').read_text()))

    def test_private_firmware_requires_both_inputs_before_creating_a_root(self):
        output, _ = self.compose()
        destination = self.root / 'incomplete-root'
        for inputs in ({'firmware_mixin': self.root / 'mixin.tar.gz'},
                       {'firmware_receipt': self.root / 'mixin.json'}):
            with self.subTest(inputs=inputs), patch.object(prepare_nfs.os, 'geteuid', return_value=0), \
                    self.assertRaisesRegex(ValueError, 'requires both'):
                prepare_nfs.prepare(output, destination, **inputs)
            self.assertFalse(destination.exists())

    def test_private_firmware_rejects_profile_receipt_and_pinned_content_mismatches(self):
        mixin, receipt, expected = self.firmware_mixin(profile='j71b')
        original = receipt.read_bytes()
        with patch.object(prepare_nfs.firmware, 'recipe_for', return_value=expected):
            with self.assertRaisesRegex(ValueError, 'not for N61'):
                prepare_nfs.read_firmware(mixin, receipt)
            record = json.loads(original)
            record['sha256'] = '0' * 64
            receipt.write_bytes(encoded(record))
            with self.assertRaisesRegex(ValueError, 'differs from its receipt'):
                prepare_nfs.read_firmware(mixin, receipt)
            receipt.write_bytes(original)
            with tarfile.open(mixin, 'w:gz') as stream:
                key = expected['outputs'][0]['destination']
                files = {key: b'changed', 'mixin.json': encoded({'schema': 1, 'profile': 'n61', 'files': {
                    key: {'bytes': 7, 'sha256': hashlib.sha256(b'changed').hexdigest()}}})}
                for key, data in files.items():
                    member = tarfile.TarInfo(key)
                    member.size = len(data)
                    stream.addfile(member, io.BytesIO(data))
            record.update(bytes=mixin.stat().st_size, sha256=sha(mixin))
            receipt.write_bytes(encoded(record))
            with self.assertRaisesRegex(ValueError, 'differs from the N61 recipe'):
                prepare_nfs.read_firmware(mixin, receipt)

    def test_private_firmware_rejects_unsafe_members_and_linked_root_parents(self):
        mixin, receipt, expected = self.firmware_mixin()
        for unsafe, kind in (('../escape', tarfile.REGTYPE),
                             ('/absolute', tarfile.REGTYPE),
                             (expected['outputs'][0]['destination'], tarfile.SYMTYPE)):
            with self.subTest(member=unsafe, kind=kind):
                with tarfile.open(mixin, 'w:gz') as stream:
                    member = tarfile.TarInfo(unsafe)
                    member.type, member.linkname = kind, '/outside'
                    stream.addfile(member)
                receipt.write_bytes(encoded({'schema': 1, 'kind': 'private-mixin',
                                             'bytes': mixin.stat().st_size, 'sha256': sha(mixin)}))
                with patch.object(prepare_nfs.firmware, 'recipe_for', return_value=expected), self.assertRaises(ValueError):
                    prepare_nfs.read_firmware(mixin, receipt)
        root, outside = self.root / 'target', self.root / 'outside'
        root.mkdir()
        outside.mkdir()
        (root / 'usr').symlink_to(outside)
        with self.assertRaises(OSError):
            prepare_nfs.stage_firmware(root, {expected['outputs'][0]['destination']: b'data'})
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
