"""Archive extraction and image assembly regression tests."""
import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
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
sys.path.insert(0, str(HARDWARE / 'runtime/j71b'))
sys.path.insert(0, str(PROJECT / 'image/j71b'))
import archive

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


class StreamingExtraction(unittest.TestCase):
    def extract(self, data, destination, digest=None, limit=100000):
        return archive.extract(io.BytesIO(data), destination, size=len(data),
                               sha256=digest or hashlib.sha256(data).hexdigest(),
                               expanded_limit=limit, ownership=False)

    def test_streams_real_files_permissions_and_root_symlinks(self):
        data = stream([('usr/lib/helper', 'file', b'hello'), ('lib', 'symlink', 'usr/lib')])
        with tempfile.TemporaryDirectory() as directory:
            result = self.extract(data, directory)
            root = Path(directory)
            self.assertEqual((root / 'lib/helper').read_bytes(), b'hello')
            self.assertEqual((root / 'usr/lib/helper').stat().st_mode & 0o777, 0o755)
            self.assertEqual(result['bytes'], len(data))

    def test_restrictive_ssh_umask_does_not_hide_implicit_public_parents(self):
        data = stream([('usr/libexec/omarchy-desktop-ready', 'file', b'helper'),
                       ('private', 'dir', 0o700), ('private/data', 'file', b'private')])
        with tempfile.TemporaryDirectory() as directory:
            previous = os.umask(0o077)
            try:
                self.extract(data, directory)
                root = Path(directory)
                for name in ('usr', 'usr/libexec', 'usr/libexec/omarchy-desktop-ready'):
                    self.assertEqual((root / name).stat().st_mode & 0o777, 0o755)
                self.assertEqual((root / 'private').stat().st_mode & 0o777, 0o700)
                from permissions import verify_session_access
                verify_session_access(root)
                (root / 'usr/libexec').chmod(0o700)
                with self.assertRaisesRegex(ValueError, 'Tablet cannot access'):
                    verify_session_access(root)
            finally:
                os.umask(previous)

    def test_traversal_symlink_hardlink_and_duplicate_attacks_do_not_escape(self):
        for entries in (
            [('../escaped', 'file', b'bad')],
            [('/escaped', 'file', b'bad')],
            [('link', 'symlink', '..'), ('link/escaped', 'file', b'bad')],
            [('hard', 'hardlink', '../escaped')],
            [('same', 'file', b'a'), ('same', 'file', b'b')],
            [('.orchard-install.json', 'file', b'fake')],
        ):
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'stage'
                root.mkdir()
                with self.assertRaises((ValueError, OSError, tarfile.TarError)):
                    self.extract(stream(entries), root)
                self.assertFalse((Path(directory) / 'escaped').exists())

    def test_corruption_truncation_and_bombs_never_succeed(self):
        data = stream([('file', 'file', b'data')])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number, (payload, digest, limit) in enumerate((
                (data, '0' * 64, 100), (data[:-8], None, 100), (data, None, 1))):
                target = root / str(number)
                target.mkdir()
                with self.assertRaises((ValueError, EOFError, OSError, tarfile.TarError)):
                    self.extract(payload, target, digest=digest, limit=limit)

    def test_hardlink_to_regular_file(self):
        data = stream([('original', 'file', b'content'), ('copy', 'hardlink', 'original')])
        with tempfile.TemporaryDirectory() as directory:
            self.extract(data, directory)
            self.assertEqual((Path(directory) / 'copy').read_bytes(), b'content')


class ImageProduction(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('ORCHARD_TEST_DIAGNOSTICS_TOOLS'),
                         'set ORCHARD_TEST_DIAGNOSTICS_TOOLS to run native Linux SSH/NSS validation')
    def test_static_diagnostics_authenticates_with_stock_arch_nss(self):
        tools = Path(os.environ['ORCHARD_TEST_DIAGNOSTICS_TOOLS']).resolve()
        image = os.environ.get('ORCHARD_TEST_ARCH_IMAGE', 'localhost/omarchy-a-arch-builder:latest')
        script = r'''
set -eu
grep -q '^group:.*systemd' /etc/nsswitch.conf
mkdir -p /root/.ssh; chmod 700 /root/.ssh
ssh-keygen -q -t ed25519 -N '' -f /tmp/client
cp /tmp/client.pub /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys
/probe/dropbearkey -t ed25519 -f /tmp/host >/dev/null 2>&1
/probe/dropbearkey -y -f /tmp/host | awk '$1=="ssh-ed25519" {print "[127.0.0.1]:2222",$1,$2}' > /tmp/known_hosts
/probe/dropbear -F -E -s -g -j -k -r /tmp/host -p 127.0.0.1:2222 >/tmp/server.log 2>&1 &
server=$!
trap 'kill "$server" 2>/dev/null || true' EXIT
python3 - <<'PYREADY'
import socket,time
end=time.monotonic()+5
while True:
 try:
  with socket.create_connection(('127.0.0.1',2222),timeout=.2):break
 except OSError:
  if time.monotonic()>=end:raise
  time.sleep(.02)
PYREADY
ssh -F /dev/null -p 2222 -i /tmp/client -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/tmp/known_hosts -o BatchMode=yes -o ConnectTimeout=2 root@127.0.0.1 true
# Exercise the actual serial bootstrap API in an isolated network namespace.
ip address add 172.16.42.1/32 dev lo
cp /probe/dropbear /usr/sbin/dropbear
cp /probe/dropbearkey /usr/bin/dropbearkey
cp /recipe/authorize-key /sbin/authorize-key
cp /recipe/start-ssh /sbin/recovery-start-ssh
chmod 755 /sbin/authorize-key /sbin/recovery-start-ssh
python3 - <<'PYBOOT'
import base64,json,pathlib,subprocess
key=' '.join(pathlib.Path('/tmp/client.pub').read_text().split()[:2])
request=base64.urlsafe_b64encode(json.dumps({'protocol':1,'public_key':key}).encode()).decode()
argv=['python3','/runtime/device.py','bootstrap',request]
first=json.loads(subprocess.check_output(argv))['result']
pid=pathlib.Path('/run/recovery/dropbear.pid').read_text()
second=json.loads(subprocess.check_output(argv))['result']
assert first==second and pathlib.Path('/run/recovery/dropbear.pid').read_text()==pid
pathlib.Path('/tmp/bootstrap_hosts').write_text(first['host']+' '+first['host_key']+'\n')
subprocess.run(['ssh','-F','/dev/null','-i','/tmp/client','-o','IdentitiesOnly=yes',
 '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/tmp/bootstrap_hosts','-o','BatchMode=yes',
 '-o','ConnectTimeout=2','root@'+first['host'],'true'],check=True)
config=pathlib.Path('/etc/orchard');config.mkdir(exist_ok=True)
(config/'release.json').write_text(json.dumps({'release':'native-test'}))
rpc=subprocess.check_output(['ssh','-F','/dev/null','-i','/tmp/client','-o','IdentitiesOnly=yes',
 '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/tmp/bootstrap_hosts','-o','BatchMode=yes',
 'root@'+first['host'],'python3 /runtime/device.py status'])
assert json.loads(rpc)['result']['ready'] is False
# Only local container processes; no physical device or host network changes.
subprocess.run(['kill',pid.strip()],check=True)
# Preserve privileged metadata through the real Linux extraction path.
import sys,io,tarfile,hashlib,os
os.umask(0o077)
sys.path.insert(0,'/runtime')
from archive import extract
from permissions import verify, verify_session_access
root=pathlib.Path('/tmp/privileged-root');root.mkdir(mode=0o755);root.chmod(0o755)
content=b'package executable'
manifest={'usr/bin/sudo':{'uid':0,'gid':0,'mode':0o4755,'type':'file','sha256':hashlib.sha256(content).hexdigest()},
          'usr/bin/wall':{'uid':0,'gid':5,'mode':0o2755,'type':'file','sha256':hashlib.sha256(content).hexdigest()}}
raw=io.BytesIO()
with tarfile.open(fileobj=raw,mode='w:gz') as archive:
 for name,data,mode,gid in [('usr/bin/sudo',content,0o4755,0),('usr/bin/wall',content,0o2755,5),('usr/libexec/omarchy-desktop-ready',b'#!/bin/sh\nexit 0\n',0o755,0),('etc/omarchy/package-privileges.json',json.dumps(manifest).encode(),0o644,0)]:
  member=tarfile.TarInfo(name);member.size=len(data);member.mode=mode;member.gid=gid;member.mtime=123
  archive.addfile(member,io.BytesIO(data))
data=raw.getvalue()
extract(io.BytesIO(data),root,size=len(data),sha256=hashlib.sha256(data).hexdigest(),expanded_limit=1000)
assert verify(root)==2
verify_session_access(root)
# Simulate tablet executing a session helper through freshly created parents.
subprocess.run(['setpriv','--reuid=1000','--regid=1000','--clear-groups',
 str(root/'usr/libexec/omarchy-desktop-ready')],check=True)
(root/'usr/bin/sudo').chmod(0o755)
try:verify(root)
except ValueError:pass
else:raise AssertionError('Missing setuid bit was accepted')
PYBOOT
'''
        with tempfile.TemporaryDirectory() as temporary:
            staged = Path(temporary) / 'runtime'
            shutil.copytree(HARDWARE / 'runtime/j71b', staged)
            for path in (PROJECT / 'image/j71b').glob('*.py'):
                shutil.copyfile(path, staged / path.name)
            result = subprocess.run(['podman', 'run', '--rm', '--network', 'none', '--cap-add', 'NET_ADMIN',
                                 '--userns', 'keep-id:uid=0,gid=0', '-v', str(tools) + ':/probe:ro',
                                 '-v', str(staged) + ':/runtime:ro',
                                 '-v', str(HARDWARE / 'boot/initramfs/recovery') + ':/recipe:ro',
                                 image, 'sh', '-c', script], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

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
            base, receipt, dropbear = root / 'base.gz', root / 'base.json', root / 'dropbear'
            base.write_bytes(data)
            receipt.write_text(json.dumps({'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}))
            dropbear.write_bytes(b'dropbear')
            overlay = root / 'overlay/usr/libexec'
            overlay.mkdir(parents=True)
            (overlay / 'omarchy-diagnostics').write_bytes(b'diagnostics')
            (overlay / 'omarchy-desktop-ready').write_bytes(b'#!/bin/sh\nexit 0\n')
            with patch.object(public_root, 'privileged_entries', return_value=privileges), \
                 patch.object(public_root, 'SYSTEM', root / 'overlay'), \
                 patch.object(public_root, 'cursor_files', return_value={'usr/libexec/omarchy-wtype': (b'wtype', 0o755)}), \
                 patch.object(public_root, 'bluetooth_files', return_value={}), \
                 patch.object(public_root, 'labwc_files', return_value={}), \
                 patch.object(public_root, 'runtime_files', return_value=('test', {
                     'usr/bin/orchard-device': (b'device', 0o755)})):
                kernel, dtb = root / 'Image.gz', root / 'j71b.dtb'
                kernel.write_bytes(b'kernel image')
                dtb.write_bytes(b'\xd0\x0d\xfe\xed')
                result = public_root.build(base, receipt, root, dropbear, root / 'release', 'test', root / 'cursor-tools',
                                           kernel=kernel, dtb=dtb)
            raw = subprocess.check_output(['zstd', '-dq', '-c', str(root / 'release/rootfs.tar.zst')])
            with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
                parent = bundle.getmember('usr/libexec')
                self.assertTrue(parent.isdir())
                self.assertEqual((parent.uid, parent.gid, parent.mode), (0, 0, 0o755))
                self.assertEqual(bundle.extractfile('usr/lib/modules/test/vmlinuz').read(), b'kernel image')
                self.assertEqual(bundle.extractfile('usr/lib/modules/test/dtb/t8010-j71b.dtb').read(), b'\xd0\x0d\xfe\xed')
                self.assertEqual(bundle.extractfile('etc/kernel/devicetree').read(), b't8010-j71b.dtb\n')
                manifest = json.load(bundle.extractfile('arch-ipad-ui-manifest.json'))
                for name, expected in replacements.items():
                    self.assertEqual(bundle.extractfile(name).read(), expected)
                    self.assertEqual(manifest[name], hashlib.sha256(expected).hexdigest())
            destination = root / 'installed'
            destination.mkdir()
            previous = os.umask(0o077)
            try:
                compressed = gzip.compress(raw)
                archive.extract(io.BytesIO(compressed), destination,
                                size=len(compressed), sha256=hashlib.sha256(compressed).hexdigest(),
                                expanded_limit=result['expanded_bytes'], ownership=False)
            finally:
                os.umask(previous)
            from permissions import verify_session_access
            verify_session_access(destination)

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
            inputs = {'loader': b'loader', 'dtb': b'dtb', 'kernel': b'kernel',
                      'initramfs': gzip.compress(b'070701' + b'\0' * 32)}
            for name, data in inputs.items():
                (root / name).write_bytes(data)
            (root / 'profile.json').write_text(json.dumps({'bootargs': 'chosen.bootargs=test\n'}))
            image = root / 'recovery.bin'
            argv = [sys.executable, '-m', 'orchard_hardware.boot.assemble', '--manifest', str(root / 'profile.json'),
                    '--output', str(image)]
            for name in inputs:
                argv.extend(['--' + name, str(root / name)])
            subprocess.run(argv, check=True, capture_output=True)
            expected = (inputs['loader'] + b'chosen.bootargs=test\n' + inputs['dtb'] + inputs['kernel'] +
                        INITRAMFS_MAGIC + struct.pack('<I', len(inputs['initramfs'])) + inputs['initramfs'])
            self.assertEqual(image.read_bytes(), expected)
            self.assertEqual(audit_recovery(image)['initramfs_sha256'], hashlib.sha256(inputs['initramfs']).hexdigest())

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
