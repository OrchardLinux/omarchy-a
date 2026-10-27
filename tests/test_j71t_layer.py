"""J71t image policy, system layer and root assembly; no device or Podman access."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import orchard_hardware
from orchard_hardware import firmware_path
from orchard_hardware.boot.initramfs.pack import record
from release.devices import SHARED_SYSTEM
from release.j71b import public_root
from release.j71b.recovery_audit import audit_runtime

PROJECT = Path(__file__).resolve().parents[1]


def policy(profile):
    paths = [str(PROJECT / 'image' / profile), str(Path(orchard_hardware.__file__).parent / 'runtime/j71b')]
    sys.path[:0] = paths
    try:
        return runpy.run_path(paths[0] + '/image_policy.py')
    finally:
        for path in paths:
            sys.path.remove(path)


class Policy(unittest.TestCase):
    def test_root_requires_j71t_helpers_and_no_charge_lease(self):
        validate = policy('j71t')['validate_handoff']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for helper in ('usr/lib/systemd/systemd', 'usr/libexec/j71t-check-platform',
                           'usr/libexec/omarchy-diagnostics'):
                (root / helper).parent.mkdir(parents=True, exist_ok=True)
                (root / helper).write_text('#!/bin/sh\n')
                (root / helper).chmod(0o755)
            validate(root)
            (root / 'usr/libexec/j71t-check-platform').chmod(0o644)
            with self.assertRaises(ValueError):
                validate(root)
        text = (PROJECT / 'image/j71t/image_policy.py').read_text()
        self.assertNotIn('j71b', text)
        self.assertNotIn('charge-lease', text)

    def test_permission_verifier_is_the_shared_j71b_policy(self):
        self.assertEqual((PROJECT / 'image/j71t/permissions.py').read_bytes(),
                         (PROJECT / 'image/j71b/permissions.py').read_bytes())


class SystemLayer(unittest.TestCase):
    def test_shared_session_files_plus_device_overlay(self):
        files = public_root.system_files('test-kernel', 'j71t')
        own = {path.relative_to(PROJECT / 'system/j71t/overlay').as_posix()
               for path in (PROJECT / 'system/j71t/overlay').rglob('*') if path.is_file()}
        self.assertEqual(set(files), set(SHARED_SYSTEM) | own)
        self.assertFalse([name for name in files if 'j71b' in name])
        for name in SHARED_SYSTEM:
            self.assertEqual(files[name][0], (PROJECT / 'system/j71b/overlay' / name).read_bytes())
        self.assertEqual(files['etc/sudoers.d/90-tablet-passwordless'][1], 0o440)
        self.assertEqual(files['usr/libexec/omarchy-screen-toggle'][1], 0o755)
        self.assertIn(b'KERNEL=="20e200000.backlight"', files['usr/lib/udev/rules.d/70-j71t-backlight.rules'][0])
        self.assertIn(b'ExecStart=/usr/libexec/j71t-check-platform',
                      files['usr/lib/systemd/system/j71t-platform-ready.service'][0])
        self.assertEqual(files['etc/polkit-1/rules.d/60-j71t-tablet-network.rules'][0],
                         (PROJECT / 'system/j71b/overlay/etc/polkit-1/rules.d/60-j71b-tablet-network.rules').read_bytes())

    def test_userspace_recipe_reuses_j71b_with_its_own_package_list(self):
        wrapper = PROJECT / 'system/j71t/build-rootfs'
        self.assertTrue(os.access(wrapper, os.X_OK))
        self.assertIn('--packages "$here/packages.txt"', wrapper.read_text())
        packages = [line for line in (PROJECT / 'system/j71t/packages.txt').read_text().splitlines()
                    if line.strip() and not line.startswith('#')]
        self.assertNotIn('linux-aarch64', packages)
        self.assertEqual(len(packages), len(set(packages)))
        subprocess.run(['bash', '-n', str(wrapper)], check=True)
        subprocess.run(['bash', '-n', str(PROJECT / 'system/j71b/build-rootfs')], check=True)


def tar_gz(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, kind, value in entries:
            member = tarfile.TarInfo(name)
            if kind == 'dir':
                member.type, member.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(member)
            elif kind == 'symlink':
                member.type, member.linkname = tarfile.SYMTYPE, value
                archive.addfile(member)
            else:
                member.size, member.mode = len(value), 0o755
                archive.addfile(member, io.BytesIO(value))
    return output.getvalue()


class PublicRoot(unittest.TestCase):
    def test_j71t_root_uses_profile_names_units_and_helpers(self):
        replacements = public_root.desktop_replacements()
        files = {name: b'old desktop content' for name in replacements}
        files.update({'usr/lib/systemd/systemd': b'systemd', 'usr/bin/sudo': b'sudo',
                      'etc/group': b'seat:x:1:\nvideo:x:2:\ninput:x:3:\n',
                      'etc/gshadow': b'seat:!*::\nvideo:!*::\ninput:!*::\n'})
        files['arch-ipad-ui-manifest.json'] = json.dumps({
            name: hashlib.sha256(files[name]).hexdigest() for name in replacements}).encode()
        parents = {str(p) for name in files for p in Path(name).parents if str(p) != '.'}
        data = tar_gz([(name, 'dir', None) for name in sorted(parents)] +
                      [(name, 'file', value) for name, value in files.items()] + [('lib', 'symlink', 'usr/lib')])
        privileges = {'usr/bin/sudo': {'uid': 0, 'gid': 0, 'mode': 0o4755, 'type': 'file',
                      'bytes': 4, 'sha256': hashlib.sha256(b'sudo').hexdigest()}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, receipt, dropbear = root / 'base.gz', root / 'base.json', root / 'dropbear'
            base.write_bytes(data)
            receipt.write_text(json.dumps({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}))
            dropbear.write_bytes(b'dropbear')
            runtime = {'usr/libexec/j71t-check-platform': (b'platform', 0o755)}
            with patch.object(public_root, 'privileged_entries', return_value=privileges), \
                 patch.object(public_root, 'cursor_files', return_value={'usr/libexec/omarchy-wtype': (b'wtype', 0o755)}), \
                 patch.object(public_root, 'bluetooth_files', return_value={}), \
                 patch.object(public_root, 'labwc_files', return_value={}), \
                 patch.object(public_root, 'runtime_files', return_value=('test', runtime)) as runtime_files:
                result = public_root.build(base, receipt, root, dropbear, root / 'release', 'test',
                                           root / 'cursor-tools', profile='j71t')
            runtime_files.assert_called_once_with(root, 'j71t')
            self.assertEqual(sorted(path.name for path in (root / 'release').iterdir()),
                             ['j71t-rootfs.json', 'j71t-rootfs.tar.zst'])
            self.assertEqual(result['profile'], 'j71t')
            self.assertEqual(json.loads((root / 'release/j71t-rootfs.json').read_text()), result)
            raw = subprocess.check_output(['zstd', '-dq', '-c', str(root / 'release/j71t-rootfs.tar.zst')])
        with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
            names = bundle.getnames()
            release = json.load(bundle.extractfile('etc/orchard/release.json'))
            wants = [name for name in names if name.startswith('etc/systemd/system/multi-user.target.wants/')]
        self.assertEqual(release['profile'], 'j71t')
        self.assertEqual(wants, ['etc/systemd/system/multi-user.target.wants/omarchy-diagnostics.service'])
        self.assertIn('etc/polkit-1/rules.d/60-j71t-tablet-network.rules', names)
        self.assertFalse([name for name in names if 'j71b' in name])


class Loader(unittest.TestCase):
    def test_loader_builds_the_selected_device_with_the_shared_splash(self):
        for device, expected in ((None, 'j71b'), ('j71t', 'j71t')):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as directory:
                fake = Path(directory) / 'orchard_hardware'
                (fake / 'boot/m1n1').mkdir(parents=True)
                (fake / '__init__.py').write_text('')
                build = fake / 'boot/m1n1/build'
                build.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$(dirname "$0")/args"\n')
                build.chmod(0o755)
                header = Path(directory) / 'logo.h'
                header.write_text('')
                subprocess.run([sys.executable, str(PROJECT / 'boot/build-loader'),
                                *(['--device', device] if device else []), '--logo-header', str(header),
                                '--output', str(Path(directory) / 'm1n1.bin')],
                               check=True, env={**os.environ, 'PYTHONPATH': directory})
                args = (fake / 'boot/m1n1/args').read_text().splitlines()
                self.assertEqual(args[0], expected)
                patch = Path(args[args.index('--extra-patch') + 1])
                self.assertEqual(patch, PROJECT / 'boot/m1n1/patches/j71b/0002-omarchy-splash.patch')
                self.assertTrue(patch.is_file())


class Recovery(unittest.TestCase):
    @staticmethod
    def image(directory, profile, config_profile=None):
        root = {'sha256': 'a' * 64, 'bytes': 1, 'expanded_bytes': 2, 'members': 1, 'compression': 'zstd'}
        files = {name: b'executable' for name in (
            'init', 'usr/bin/orchard-device', 'usr/bin/python3', 'sbin/capture-adt',
            'sbin/authorize-key', 'sbin/recovery-start-ssh', 'usr/sbin/blkid', 'usr/sbin/sfdisk',
            'usr/sbin/mke2fs', 'etc/mke2fs.conf')}
        for name in ('device.py', 'archive.py', 'staging.py', 'handoff.py', 'image_policy.py',
                     'permissions.py', 'storage.py', 'identity.py', 'adt.py'):
            files['usr/libexec/orchard-' + profile + '/' + name] = b'# runtime\n'
        files['etc/orchard/release.json'] = json.dumps({'root': root, 'release': 'test-1', 'protocol': 1,
                                                       'profile': config_profile or profile}).encode()
        files['etc/orchard/firmware.json'] = firmware_path(profile).read_bytes()
        files['etc/orchard/public.SHA256SUMS'] = ''.join(
            hashlib.sha256(data).hexdigest() + '  /' + name + '\n' for name, data in sorted(files.items())).encode()
        output = io.BytesIO()
        entries = sorted(files.items())
        for index, (name, data) in enumerate(entries, 1):
            record(output, index, name, stat.S_IFREG | 0o755, data)
        record(output, len(entries) + 1, 'TRAILER!!!', 0, b'')
        output.write(b'\0' * 512)
        image = Path(directory) / 'j71t-recovery.bin'
        image.write_bytes(gzip.compress(output.getvalue()))
        Path(str(image) + '.json').write_text(json.dumps({'components': [
            {'name': 'initramfs', 'offset': 0, 'bytes': image.stat().st_size}]}))
        return image, root

    def test_recovery_is_locked_to_the_j71t_runtime_and_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            image, root = self.image(directory, 'j71t')
            self.assertGreater(audit_runtime(image, root, 'test-1', 'j71t')['members'], 0)
            with self.assertRaises(ValueError):
                audit_runtime(image, root, 'test-1')
        with tempfile.TemporaryDirectory() as directory:
            image, root = self.image(directory, 'j71t', config_profile='j71b')
            with self.assertRaises(ValueError):
                audit_runtime(image, root, 'test-1', 'j71t')


if __name__ == '__main__':
    unittest.main()
