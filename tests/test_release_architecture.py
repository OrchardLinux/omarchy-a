"""Release boundaries reject a component or platform from another ISA."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from release import audit, build, manifests, public_root


def elf(architecture):
    arm = architecture == 'armv7h'
    raw = bytearray(52 if arm else 64)
    raw[:7] = b'\x7fELF' + bytes((1 if arm else 2, 1, 1))
    struct.pack_into('<HHI', raw, 16, 2, 40 if arm else 183, 1)
    struct.pack_into('<H', raw, 40 if arm else 52, len(raw))
    if arm:
        struct.pack_into('<I', raw, 36, 0x05000400)
    return bytes(raw)


def static_elf(architecture):
    arm = architecture == 'armv7h'
    data = bytearray(elf(architecture))
    offset, size = len(data), 32 if arm else 56
    data.extend(bytes(size))
    struct.pack_into('<I' if arm else '<Q', data, 28 if arm else 32, offset)
    struct.pack_into('<HH', data, 42 if arm else 54, size, 1)
    struct.pack_into('<I', data, offset, 1)
    return bytes(data)


class ReleaseArchitecture(unittest.TestCase):
    def args(self, architecture, platforms):
        return argparse.Namespace(architecture=architecture, platform=platforms, kernel_dir=None)

    def test_platform_selection_cannot_cross_root_architecture(self):
        inputs = {'platforms': {'apple-16k': {'kernel': '/arm64'},
                               'apple-armv7': {'kernel': '/arm'}}}
        self.assertEqual(build.kernels(self.args('armv7h', ['apple-armv7']), inputs),
                         {'apple-armv7': Path('/arm')})
        for architecture, selection in (('armv7h', ['apple-16k']), ('aarch64', ['apple-armv7']),
                                        ('armv7h', None), ('aarch64', None)):
            with self.subTest(architecture=architecture, selection=selection), \
                    self.assertRaisesRegex(ValueError, 'architecture differs'):
                build.kernels(self.args(architecture, selection), inputs)

    def test_input_architecture_must_agree_with_platform(self):
        inputs = {'platforms': {'apple-armv7': {'kernel': '/arm', 'architecture': 'arm64'}}}
        with self.assertRaisesRegex(ValueError, 'input architecture differs'):
            build.kernels(self.args('armv7h', ['apple-armv7']), inputs)

    def test_armv7_components_come_from_its_platform_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {key: root / key for key in ('loader', *build.TOOLS)}
            for path in paths.values():
                path.write_bytes(b'component')
            args = argparse.Namespace(architecture='armv7h', loader=None,
                                      **{key: None for key in build.TOOLS})
            row = {'architecture': 'arm', 'image': 'zImage',
                   'boards': {'p105': 's5l8942x-p105'},
                   'loader': {'kind': 'cascadia', 'file': str(paths['loader'])},
                   'tools': {key: str(paths[key]) for key in build.TOOLS}}
            inputs = {'platforms': {'apple-armv7': row}}
            selected = build.platform_inputs(args, 'apple-armv7', inputs)
            self.assertEqual(selected.kernel_image, 'zImage')
            self.assertEqual(selected.loader, paths['loader'])
            self.assertEqual(selected.busybox, paths['busybox'])
            wrong_board = argparse.Namespace(**vars(args), device='j1')
            with self.assertRaisesRegex(ValueError, 'input boards differ'):
                build.platform_inputs(wrong_board, 'apple-armv7', inputs)
            row['loader']['kind'] = 'm1n1'
            with self.assertRaisesRegex(ValueError, 'loader kind'):
                build.platform_inputs(args, 'apple-armv7', inputs)

    def test_lwvm_root_requires_a_native_static_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('loader', *build.TOOLS):
                (root / name).write_bytes(b'component')
            args = argparse.Namespace(architecture='armv7h', loader=None)
            row = {'root_format': 'lwvm', 'boards': {'p105': 's5l8942x-p105'},
                   'loader': {'kind': 'cascadia', 'file': str(root / 'loader')},
                   'tools': {name: str(root / name) for name in build.TOOLS}}
            document = {'platforms': {'apple-armv7': row}}
            with self.assertRaisesRegex(ValueError, 'requires tools.lwvm'):
                build.platform_inputs(args, 'apple-armv7', document)
            helper = root / 'orchard-lwvm'
            row['tools']['lwvm'] = str(helper)
            helper.write_bytes(static_elf('armv7h'))
            self.assertEqual(build.platform_inputs(args, 'apple-armv7', document).lwvm, helper)
            helper.write_bytes(static_elf('aarch64'))
            with self.assertRaisesRegex(ValueError, 'LwVM helper.*ELF'):
                build.platform_inputs(args, 'apple-armv7', document)
            dynamic = bytearray(static_elf('armv7h'))
            struct.pack_into('<I', dynamic, 52, 3)
            helper.write_bytes(dynamic)
            with self.assertRaisesRegex(ValueError, 'ELF interpreter'):
                build.platform_inputs(args, 'apple-armv7', document)

    def test_static_helper_checks_dynamic_dependencies_and_table_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'helper'
            data = bytearray(static_elf('armv7h'))
            data.extend(bytes(32))
            struct.pack_into('<H', data, 44, 2)
            struct.pack_into('<II', data, 84, 2, 116)
            struct.pack_into('<I', data, 84 + 16, 16)
            data.extend(struct.pack('<4I', 1, 0, 0, 0))
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'shared library'):
                build.check_static_elf(path, 'armv7h')
            struct.pack_into('<I', data, 84 + 16, 32)
            path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'dynamic segment'):
                build.check_static_elf(path, 'armv7h')

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

    def test_recovery_access_tools_must_match_target(self):
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

    @unittest.skipUnless(shutil.which('zstd'), 'zstd is required for root compression')
    def test_base_binary_with_foreign_isa_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / 'base.gz'
            with tarfile.open(base, 'w:gz') as archive:
                member = tarfile.TarInfo('usr/lib/systemd/systemd')
                payload = elf('aarch64')
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            receipt = root / 'base.json'
            receipt.write_text(json.dumps({'architecture': 'armv7h', 'bytes': base.stat().st_size,
                                           'sha256': public_root.sha(base)}))
            with patch.object(public_root, 'privileged_entries', return_value={}), \
                    patch.object(public_root, 'cursor_files', return_value={}), \
                    patch.object(public_root, 'bluetooth_files', return_value={}), \
                    patch.object(public_root, 'labwc_files', return_value={}), \
                    patch.object(public_root, 'system_files', return_value={}), \
                    self.assertRaisesRegex(ValueError, 'systemd.*armv7h'):
                public_root.build(base, receipt, root / 'out', 'test', root, architecture='armv7h')
            self.assertFalse((root / 'out').exists())

    @unittest.skipUnless(shutil.which('zstd'), 'zstd is required for root compression')
    def test_armv7_root_accepts_link_objects_and_preserves_package_privileges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replacements = public_root.desktop_replacements()
            contents = {name: b'old desktop' for name in replacements}
            relocatable = bytearray(elf('armv7h'))
            struct.pack_into('<H', relocatable, 16, 1)
            struct.pack_into('<I', relocatable, 36, 0x05000000)
            contents.update({'usr/lib/systemd/systemd': elf('armv7h'), 'usr/lib/crt1.o': bytes(relocatable),
                             'usr/bin/sudo': elf('armv7h'),
                             'etc/group': b'seat:x:1:\nvideo:x:2:\ninput:x:3:\n',
                             'etc/gshadow': b'seat:!*::\nvideo:!*::\ninput:!*::\n'})
            contents['arch-ipad-ui-manifest.json'] = json.dumps({
                name: hashlib.sha256(contents[name]).hexdigest() for name in replacements}).encode()
            parents = {str(parent) for name in contents for parent in PurePosixPath(name).parents
                       if str(parent) != '.'}
            base = root / 'base.gz'
            with tarfile.open(base, 'w:gz') as archive:
                for name in sorted(parents):
                    member = tarfile.TarInfo(name)
                    member.type, member.mode = tarfile.DIRTYPE, 0o755
                    archive.addfile(member)
                for name, data in contents.items():
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(data), 0o755
                    archive.addfile(member, io.BytesIO(data))
                member = tarfile.TarInfo('lib')
                member.type, member.linkname = tarfile.SYMTYPE, 'usr/lib'
                archive.addfile(member)
            receipt = root / 'base.json'
            receipt.write_text(json.dumps({'architecture': 'armv7h', 'bytes': base.stat().st_size,
                                           'sha256': public_root.sha(base)}))
            privileges = {'usr/bin/sudo': {'uid': 0, 'gid': 0, 'mode': 0o4755, 'type': 'file',
                                          'bytes': len(elf('armv7h')),
                                          'sha256': hashlib.sha256(elf('armv7h')).hexdigest()}}
            with patch.object(public_root, 'privileged_entries', return_value=privileges), \
                    patch.object(public_root, 'cursor_files', return_value={}), \
                    patch.object(public_root, 'bluetooth_files', return_value={}), \
                    patch.object(public_root, 'labwc_files', return_value={}), \
                    patch.object(public_root, 'system_files', return_value={}):
                result = public_root.build(base, receipt, root / 'out', 'test', root, architecture='armv7h')
            self.assertEqual(result['architecture'], 'armv7h')
            raw = subprocess.check_output(['zstd', '-dq', '-c', str(root / 'out/rootfs.tar.zst')])
            with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
                self.assertEqual(archive.extractfile('usr/lib/crt1.o').read(), bytes(relocatable))
                self.assertEqual(archive.getmember('usr/bin/sudo').mode, 0o4755)

    def test_armv7_manifest_uses_its_boot_method_without_pongo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('rootfs.tar.zst', 'recovery.bin', 'platform.tar.gz'):
                (root / name).write_bytes(name.encode())
            root_record = {'architecture': 'armv7h', 'compression': 'zstd', 'expanded_bytes': 10, 'members': 1}
            layer = manifests.receipt(root / 'platform.tar.gz')
            layer.update(compression='gzip', expanded_bytes=10, members=1, kernel_release='6.12.0')
            platforms = {'apple-armv7': {'boards': ['p105'], 'boot': manifests.receipt(root / 'recovery.bin'),
                                         'layer': layer}}
            path = manifests.write(root, 'armv7-test', root_record, platforms,
                                   {'commit': 'a' * 40, 'modified': False}, architecture='armv7h')
            document = manifests.tomllib.loads(path.read_text())
            self.assertEqual(document['boot_method'], 'recovery-autogo')
            self.assertNotIn('pongo', document)
            self.assertEqual(manifests.read_release(path)['architecture'], 'armv7h')
            mixed = {**platforms, 'apple-16k': platforms['apple-armv7']}
            with self.assertRaisesRegex(ValueError, 'root architecture'):
                manifests.write(root, 'mixed', root_record, mixed, {}, architecture='armv7h')

    def test_armv7_recovery_uses_platform_and_zimage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dtbs').mkdir()
            (root / 'dtbs/s5l8942x-p105.dtb').write_bytes(b'\xd0\x0d\xfe\xed')
            args = argparse.Namespace(architecture='armv7h', output=root, orchard=root, kernel_image='zImage',
                                      lwvm=root / 'orchard-lwvm',
                                      **{name: root / name for name in ('base', 'base_receipt', 'loader', *build.TOOLS)})
            with patch.object(build.snapshot, 'command') as command:
                build.recovery(args, 'apple-armv7', root, {'p105': 's5l8942x-p105'}, root / 'rootfs.json')
            argv = command.call_args.args
            self.assertIn('--platform', argv)
            self.assertIn('apple-armv7', argv)
            self.assertIn(str(root / 'zImage'), argv)
            self.assertNotIn('--logo', argv)
            self.assertEqual(argv[argv.index('--lwvm') + 1], str(root / 'orchard-lwvm'))

    def test_lwvm_platform_uses_the_selected_rescue_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = argparse.Namespace(architecture='armv7h', output=root, orchard=root, device='p105',
                                      busybox=root / 'busybox', dropbear=root / 'dropbear',
                                      lwvm=root / 'orchard-lwvm')

            def produce(*argv, **kwargs):
                Path(argv[argv.index('--receipt') + 1]).write_text('{}')

            with patch.object(build.snapshot, 'command', side_effect=produce) as command:
                build.layer(args, 'apple-armv7', root / 'kernel')
            argv = command.call_args.args
            self.assertEqual(argv[argv.index('--lwvm') + 1], root / 'orchard-lwvm')
            self.assertEqual(argv[argv.index('--rescue-tools') + 1], root)

    def cascadia_fixture(self, root):
        # Exercise the companion Orchard producer's real framing contract.
        from orchard.image import cascadia
        described = {'schema': 1, 'load_address': 0x80000000, 'kernel_offset': 0x8000,
                     'watchdog_address': 0x3c100000, 'l2_address': 0xb0000000,
                     'ram_start': 0x80000000, 'ram_end': 0xa0000000,
                     'initrd_address': 0x90000000, 'initrd_limit': 0x98000000}
        loader = bytearray(cascadia.CONFIG_OFFSET + cascadia.CONFIG.size)
        loader[:4] = bytes.fromhex('c0000cf1')
        values = dict.fromkeys(cascadia.CONFIG_FIELDS, 0)
        values.update(described)
        values.update(magic=b'CB32', version=1, header_size=cascadia.CONFIG.size)
        cascadia.CONFIG.pack_into(loader, cascadia.CONFIG_OFFSET,
                                 *(values[key] for key in cascadia.CONFIG_FIELDS))
        kernel = bytearray(128)
        struct.pack_into('<3I', kernel, 36, 0x016f2818, 0, len(kernel))
        struct.pack_into('<3I', kernel, 0x30, 0x04030201, 0x45454545, 0x40)
        struct.pack_into('<7I', kernel, 0x40, 6, 0x5a534c4b, 0x60, 0x1000, 0x8000, 0x1000, 0)
        struct.pack_into('<I', kernel, 0x60, 0x100000)
        tree = {'name': '', 'properties': {'#address-cells': struct.pack('>I', 1)}, 'children': []}
        data, receipt = cascadia.assemble(bytes(loader), bytes(kernel), cascadia.write_fdt(tree),
                                         gzip.compress(b'070701'), described, 'rdinit=/init')
        image = root / 'recovery.bin'
        image.write_bytes(data)
        Path(str(image) + '.json').write_text(json.dumps(receipt))
        return image, receipt

    def test_cascadia_recovery_audit_checks_actual_component_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            image, receipt = self.cascadia_fixture(Path(directory))
            self.assertEqual(audit.audit_recovery(image, 'armv7h')['initramfs_encoding'], 'cascadia-dtb')
            kernel = next(row for row in receipt['components'] if row['name'] == 'kernel')
            with image.open('r+b') as output:
                output.seek(kernel['offset'] + 36)
                output.write(b'FAIL')
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                audit.audit_recovery(image, 'armv7h')

    def test_cascadia_config_is_checked_after_component_hashes_agree(self):
        with tempfile.TemporaryDirectory() as directory:
            image, receipt = self.cascadia_fixture(Path(directory))
            raw = bytearray(image.read_bytes())
            # Forge a valid configuration CRC naming the wrong DTB position.
            struct.pack_into('<I', raw, 0x7f00 + 20, 0x8100)
            import zlib
            struct.pack_into('<I', raw, 0x7f00 + 64, zlib.crc32(raw[0x7f00:0x7f00 + 64]))
            image.write_bytes(raw)
            loader = receipt['components'][0]
            loader['sha256'] = hashlib.sha256(raw[:loader['bytes']]).hexdigest()
            receipt['image_sha256'] = hashlib.sha256(raw).hexdigest()
            Path(str(image) + '.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, 'addresses differ|configuration differs'):
                audit.audit_recovery(image, 'armv7h')



if __name__ == '__main__':
    unittest.main()
