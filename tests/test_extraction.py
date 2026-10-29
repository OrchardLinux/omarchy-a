"""Archive extraction and image assembly regression tests."""
import gzip
import hashlib
import io
import json
import os
import subprocess
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import orchard_hardware

PROJECT = Path(__file__).resolve().parents[1]
HARDWARE = Path(orchard_hardware.__file__).parent

def stream(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as bundle:
        for name, kind, value in entries:
            member = tarfile.TarInfo(name)
            if kind in ('file', 'setuid'):
                member.size, member.mode = len(value), 0o4755 if kind == 'setuid' else 0o755
                bundle.addfile(member, io.BytesIO(value))
            elif kind == 'dir':
                member.type, member.mode = tarfile.DIRTYPE, value
                bundle.addfile(member)
                continue
            else:
                member.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
                member.linkname = value
                bundle.addfile(member)
    return output.getvalue()


class ImageProduction(unittest.TestCase):
    def test_public_producer_bakes_parent_directories_and_desktop_updates(self):
        from release.j71b import public_root
        from pathlib import PurePosixPath
        replacements = public_root.desktop_replacements()
        files = {name: b'old desktop content' for name in replacements}
        files.update({'usr/lib/systemd/systemd': b'systemd', 'usr/bin/sudo': b'sudo',
                      'etc/group': b'seat:x:1:\nvideo:x:2:\ninput:x:3:\n',
                      'etc/gshadow': b'seat:!*::\nvideo:!*::\ninput:!*::\n'})
        files['arch-ipad-ui-manifest.json'] = json.dumps({
            name: hashlib.sha256(files[name]).hexdigest() for name in replacements}).encode()
        parents = {str(p) for name in files for p in PurePosixPath(name).parents if str(p) != '.'}
        data = stream([(name, 'dir', 0o755) for name in sorted(parents)] +
                      [(name, 'file', value) for name, value in files.items()] + [('lib', 'symlink', 'usr/lib')])
        privileges = {'usr/bin/sudo': {'uid': 0, 'gid': 0, 'mode': 0o4755, 'type': 'file',
                      'bytes': 4, 'sha256': hashlib.sha256(b'sudo').hexdigest()}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, receipt = root / 'base.gz', root / 'base.json'
            base.write_bytes(data)
            receipt.write_text(json.dumps({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}))
            overlay = root / 'overlay/usr/libexec'
            overlay.mkdir(parents=True)
            (overlay / 'omarchy-desktop-ready').write_bytes(b'#!/bin/sh\nexit 0\n')
            with patch.object(public_root, 'privileged_entries', return_value=privileges), \
                 patch.object(public_root, 'SYSTEM', root / 'overlay'), \
                 patch.object(public_root, 'cursor_files', return_value={'usr/libexec/omarchy-wtype': (b'wtype', 0o755)}), \
                 patch.object(public_root, 'bluetooth_files', return_value={}), \
                 patch.object(public_root, 'labwc_files', return_value={}), \
                 patch.object(public_root, 'runtime_files', return_value=('test', {
                     'usr/lib/modules/test/modules.dep': (b'', 0o644)})):
                kernel, dtbs = root / 'Image.gz', root / 'dtbs'
                kernel.write_bytes(b'kernel image')
                dtbs.mkdir()
                for board in ('t8010-j71b', 't8010-j171'):
                    (dtbs / (board + '.dtb')).write_bytes(b'\xd0\x0d\xfe\xed' + board.encode())
                public_root.build(base, receipt, root, root / 'release', 'test', root / 'cursor-tools',
                                  kernel=kernel, dtbs=dtbs)
            raw = subprocess.check_output(['zstd', '-dq', '-c', str(root / 'release/rootfs.tar.zst')])
            with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
                parent = bundle.getmember('usr/libexec')
                self.assertTrue(parent.isdir())
                self.assertEqual((parent.uid, parent.gid, parent.mode), (0, 0, 0o755))
                self.assertEqual(bundle.extractfile('usr/lib/modules/test/vmlinuz').read(), b'kernel image')
                # Every board's DTB; the installer names the board in /etc/kernel/devicetree.
                for board in ('t8010-j71b', 't8010-j171'):
                    self.assertEqual(bundle.extractfile(f'usr/lib/modules/test/dtb/{board}.dtb').read(),
                                     b'\xd0\x0d\xfe\xed' + board.encode())
                self.assertNotIn('etc/kernel/devicetree', bundle.getnames())
                manifest = json.load(bundle.extractfile('arch-ipad-ui-manifest.json'))
                for name, expected in replacements.items():
                    self.assertEqual(bundle.extractfile(name).read(), expected)
                    self.assertEqual(manifest[name], hashlib.sha256(expected).hexdigest())
                # The tablet session reaches its readiness helper through public parents.
                for name in ('usr', 'usr/libexec', 'usr/libexec/omarchy-desktop-ready'):
                    self.assertEqual(bundle.getmember(name).mode & 0o755, 0o755, name)
                # A directly booted system carries no recovery device runtime or USB diagnostics.
                names = bundle.getnames()
                self.assertFalse([n for n in names if 'orchard-j71b' in n or 'omarchy-diagnostics' in n or
                                  n in ('usr/bin/orchard-device', 'usr/libexec/omarchy-dropbear')])

    @unittest.skipUnless(__import__('shutil').which('node'), 'node is required for desktop model validation')
    def test_battery_startup_and_bluetooth_name_fallback_models(self):
        script = r'''
const assert = require('node:assert/strict');
const model = require(process.argv[1]);
const snapshot = model.parseKeyValue('percentage\t73%\nexternal_power\tconnected\n');
assert.equal(model.batteryPercentage(null, snapshot), 73);
assert.equal(model.batteryFraction(null, snapshot), .73);
assert.equal(model.batteryPercentage(null, {percentage:'0%'}), 0);
assert.equal(model.batteryPercentage(null, {}), null);
assert.equal(model.batteryPercentage(null, {percentage:'101%'}), null);
assert.equal(model.batteryPercentage({isPresent:true, percentage:.42}, {}), 42);
const bluetooth = require(process.argv[2]);
const address = 'AA:BB:CC:DD:EE:FF';
assert.equal(bluetooth.deviceLabel({deviceName:address,name:'Desk speaker',address}), 'Desk speaker');
assert.equal(bluetooth.deviceLabel({name:address,deviceName:'Headphones',address}), 'Headphones');
assert.equal(bluetooth.deviceLabel({name:'My alias',deviceName:'Factory name',address}), 'My alias');
assert.equal(bluetooth.deviceLabel({name:address,deviceName:address,address}), address);
assert.equal(bluetooth.hasHumanName({name:address,deviceName:address}), false);
assert.equal(bluetooth.deviceLabel(bluetooth.deviceRow({name:'My alias',deviceName:address,address})), 'My alias');
'''
        subprocess.run(['node', '-e', script, str(PROJECT / 'desktop/shell/shell/plugins/panels/power/Model.js'),
                        str(PROJECT / 'desktop/shell/shell/plugins/panels/bluetooth/Model.js')], check=True)

    def test_cursor_component_is_content_verified_before_packaging(self):
        from release.j71b.public_root import cursor_files
        pin = json.loads((PROJECT / 'desktop/cursor/wtype.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('wtype', 'LICENSE'):
                (root / name).write_bytes(name.encode())
            record = {'schema': 1, 'architecture': 'aarch64', 'source': pin,
                      'files': {name: hashlib.sha256(name.encode()).hexdigest() for name in ('wtype', 'LICENSE')}}
            (root / 'manifest.json').write_text(json.dumps(record))
            self.assertEqual(cursor_files(root)['usr/libexec/omarchy-wtype'], (b'wtype', 0o755))
            (root / 'wtype').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'differs from receipt'):
                cursor_files(root)

    def test_package_privileges_restore_only_matching_package_content(self):
        from release.package_permissions import parse_mtree, apply
        data = b'package executable'
        digest = hashlib.sha256(data).hexdigest()
        records = dict(parse_mtree('#mtree\n/set type=file uid=0 gid=0 mode=644\n'
                       './usr/bin/sudo mode=4755 size=' + str(len(data)) + ' sha256digest=' + digest + '\n'))
        member = tarfile.TarInfo('usr/bin/sudo')
        member.uid, member.gid, member.mode = 501, 20, 0o755
        apply(member, data, records[member.name], {})
        self.assertEqual((member.uid, member.gid, member.mode), (0, 0, 0o4755))
        with self.assertRaisesRegex(ValueError, 'content differs'):
            apply(member, b'X' * len(data), records[member.name], {})

    def test_recovery_framing_preserves_the_compressed_initramfs(self):
        import struct
        from orchard_hardware.boot.assemble import INITRAMFS_MAGIC
        from release.j71b.audit import audit_recovery
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fdt = b'\xd0\x0d\xfe\xed'
            inputs = {'loader': b'loader', 'dtb': fdt + b'a', 'dtb2': fdt + b'b', 'kernel': b'kernel',
                      'initramfs': gzip.compress(b'070701' + b'\0' * 32)}
            for name, data in inputs.items():
                (root / name).write_bytes(data)
            (root / 'profile.json').write_text(json.dumps({'bootargs': 'chosen.bootargs=test\n'}))
            image = root / 'recovery.bin'
            argv = [sys.executable, '-m', 'orchard_hardware.boot.assemble', '--manifest', str(root / 'profile.json'),
                    '--output', str(image)]
            for name in inputs:
                argv.extend(['--' + name.rstrip('2'), str(root / name)])
            subprocess.run(argv, check=True, capture_output=True)
            expected = (inputs['loader'] + b'chosen.bootargs=test\n' + inputs['dtb'] + inputs['dtb2'] + inputs['kernel'] +
                        INITRAMFS_MAGIC + struct.pack('<I', len(inputs['initramfs'])) + inputs['initramfs'])
            self.assertEqual(image.read_bytes(), expected)
            audit = audit_recovery(image)
            self.assertEqual(audit['initramfs_sha256'], hashlib.sha256(inputs['initramfs']).hexdigest())
            self.assertEqual(audit['dtbs'], 2)

    def test_recovery_adt_endpoint_owns_size_and_exact_binary_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = root / 'mtd'
            table.write_text('dev: size erasesize name\nmtd3: 00000004 00000001 "adt"\n')
            (root / 'mtd3').write_bytes(b'\x00\xff\r\n')
            env = {**os.environ, 'ADT_MTD_TABLE': str(table), 'ADT_MTD_DEV': str(root)}
            endpoint = HARDWARE / 'boot/initramfs/recovery/capture-adt'
            size = subprocess.check_output(['sh', str(endpoint), '--size'], env=env)
            self.assertEqual(int(size.strip(), 16), 4)
            self.assertEqual(subprocess.check_output(['sh', str(endpoint)], env=env), b'\x00\xff\r\n')
            table.write_text(table.read_text() + 'mtd4: 00000004 00000001 "adt"\n')
            result = subprocess.run(['sh', str(endpoint)], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')
