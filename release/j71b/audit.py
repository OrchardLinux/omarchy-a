"""Offline audit of finished assets: namespace safety, integrity and boot contracts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import struct
import tarfile

from orchard_hardware.boot.assemble import INITRAMFS_MAGIC
from orchard_hardware import firmware_path
from release.manifests import read_release

from .public_root import sha
from .runtime import PROJECT
from .recovery_audit import audit_runtime


def audit_recovery(image):
    receipt = json.loads(Path(str(image) + '.json').read_text())
    parts, dtbs, end = {}, 0, 0
    with image.open('rb') as stream:
        for row in receipt['components']:
            # One DTB per device the recovery boots; every other part once.
            if (row['name'] in parts and row['name'] != 'dtb') or row['offset'] != end or row['bytes'] <= 0:
                raise ValueError('Invalid recovery component boundaries')
            data = stream.read(row['bytes'])
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Recovery component integrity mismatch: ' + row['name'])
            if row['name'] == 'dtb':
                if not data.startswith(b'\xd0\x0d\xfe\xed'):
                    raise ValueError('Recovery DTB component is not a devicetree')
                dtbs += 1
            parts[row['name']] = (row, data[:32])
            end += row['bytes']
    if end != image.stat().st_size or receipt['image_sha256'] != sha(image):
        raise ValueError('Recovery image receipt mismatch')
    if set(parts) != {'loader', 'bootargs', 'dtb', 'kernel', 'initramfs_header', 'initramfs'}:
        raise ValueError('Missing recovery component')
    header = parts['initramfs_header'][1]
    size = parts['initramfs'][0]['bytes']
    if (receipt.get('initramfs_encoding') != 'm1n1_initramfs' or
            header != INITRAMFS_MAGIC + struct.pack('<I', size) or
            not parts['initramfs'][1].startswith(b'\x1f\x8b')):
        raise ValueError('Initramfs is not framed for Linux decompression')
    return {'passed': True, 'dtbs': dtbs, 'initramfs_encoding': receipt['initramfs_encoding'],
            'compressed_bytes': size, 'initramfs_sha256': parts['initramfs'][0]['sha256']}


def audit(manifest):
    record = read_release(manifest)
    if record.get('schema') != 1 or record.get('protocol') != 1 or record.get('profile') != 'j71b':
        raise ValueError('Incompatible release manifest')
    paths = {}
    for role, item in record['assets'].items():
        relative = PurePosixPath(item['file'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Asset escapes release directory')
        path = manifest.parent / relative
        if path.is_symlink() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('Asset integrity mismatch: ' + role)
        paths[role] = path
    recovery = audit_recovery(paths['recovery'])
    runtime = audit_runtime(paths['recovery'], record['assets']['root'], record['release'])
    recovery['runtime_members_verified'] = runtime['members']
    hashes, links, modes, owners, groups, sizes = {}, {}, {}, {}, {}, {}
    names, ancestors, directories = set(), set(), set()
    desktop = public = privileges = cursor = bluetooth = labwc = None
    recipe = json.loads(firmware_path('j71b').read_text())
    private = {item['destination'] for item in recipe['outputs']}
    with subprocess.Popen(['zstd', '-d', '-q', '-c', str(paths['root'])], stdout=subprocess.PIPE) as decoder:
        with tarfile.open(fileobj=decoder.stdout, mode='r|') as archive:
            for member in archive:
                name = member.name
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or name in names:
                    raise ValueError('Unsafe/duplicate root member: ' + name)
                names.add(name)
                ancestors.update(str(p) for p in path.parents if str(p) != '.')
                modes[name], owners[name], groups[name], sizes[name] = member.mode, member.uid, member.gid, member.size
                if name.removeprefix('usr/') in private:
                    raise ValueError('Private firmware found in public root')
                if member.issym() or member.islnk():
                    links[name] = (member.issym(), member.linkname)
                elif member.isfile():
                    data = archive.extractfile(member).read()
                    hashes[name] = hashlib.sha256(data).hexdigest()
                    if name == 'arch-ipad-ui-manifest.json':
                        desktop = json.loads(data)
                    if name == 'etc/omarchy/cursor-helper.json':
                        cursor = json.loads(data)
                    if name == 'etc/omarchy/bluetooth-helper.json':
                        bluetooth = json.loads(data)
                    if name == 'etc/omarchy/labwc-helper.json':
                        labwc = json.loads(data)
                    if name == 'etc/omarchy/package-privileges.json':
                        privileges = json.loads(data)
                    if name == 'etc/orchard/public.SHA256SUMS':
                        public = data.decode()
                elif member.isdir():
                    directories.add(name)
                else:
                    raise ValueError('Special root member')
        if decoder.wait():
            raise ValueError('Root decompression failed')
    if ancestors - directories:
        raise ValueError('Missing explicit parent directory metadata: ' + ', '.join(sorted(ancestors - directories)))
    for name in ('usr', 'usr/libexec'):
        if modes.get(name, 0) & 0o555 != 0o555:
            raise ValueError('Tablet session cannot traverse helper directory: ' + name)
    if any(name in ancestors for name in links):
        raise ValueError('Archive link is also a parent directory')
    for name, (symbolic, target) in links.items():
        if not symbolic:
            target_path = PurePosixPath(target)
            if target_path.is_absolute() or '..' in target_path.parts or str(target_path) not in hashes:
                raise ValueError('Hardlink is not to a regular in-root member: ' + name)
    if not desktop or not public:
        raise ValueError('Missing desktop/runtime integrity manifest')
    for name, expected in desktop.items():
        if hashes.get(name) != expected:
            raise ValueError('Desktop content mismatch: ' + name)
    if public != runtime['public']:
        raise ValueError('Root/recovery public runtime manifests differ')
    for line in public.splitlines():
        expected, name = line.split('  ', 1)
        if hashes.get(name.lstrip('/')) != expected or runtime['hashes'].get(name.lstrip('/')) != expected:
            raise ValueError('Public runtime mismatch: ' + name)
    verify_tablet_sudo(hashes, modes, owners, groups)
    if not privileges or privileges.get('usr/bin/sudo', {}).get('mode') != 0o4755:
        raise ValueError('Missing package-defined sudo permissions')
    for name, expected in privileges.items():
        if (modes.get(name), owners.get(name), groups.get(name)) != (expected['mode'], expected['uid'], expected['gid']):
            raise ValueError('Privileged package metadata mismatch: ' + name)
        if expected['type'] == 'file':
            actual = hashes.get(name)
            if name in links and not links[name][0]:
                actual = hashes.get(links[name][1])
            if actual != expected['sha256']:
                raise ValueError('Privileged package file differs: ' + name)
    if not cursor or hashes.get('usr/libexec/omarchy-wtype') != cursor['files'].get('wtype'):
        raise ValueError('Startup cursor helper differs from build receipt')
    if hashes.get('usr/share/licenses/omarchy-wtype/LICENSE') != cursor['files'].get('LICENSE'):
        raise ValueError('Missing startup cursor helper license')
    verify_bluetooth(bluetooth, hashes, modes, owners, groups)
    verify_labwc(labwc, hashes, modes, owners, groups)
    if 'home/tablet/.local/share/omarchy-ipad/shell/bluetooth-pairing/shell.qml' not in desktop:
        raise ValueError('Pairing UI is absent from desktop integrity manifest')
    for name in ('omarchy-desktop-ready', 'omarchy-wtype', 'omarchy-screen-toggle', 'omarchy-bluetooth-pair'):
        if modes.get('usr/libexec/' + name) != 0o755:
            raise ValueError('Required helper is not executable: ' + name)
    if links.get('lib') != (True, 'usr/lib') or owners.get('home/tablet') != 1000 or sizes.get('etc/machine-id') != 0:
        raise ValueError('Invalid root/session contract')
    return {'passed': True, 'hardware_validated': False, 'release': record['release'],
            'members': len(names), 'desktop_files_verified': len(desktop),
            'root_sha256': record['assets']['root']['sha256'], 'recovery': recovery,
            'privileged_entries_verified': len(privileges)}


def verify_labwc(record, hashes, modes, owners, groups):
    pin = json.loads((PROJECT / 'desktop/labwc/source.json').read_text())
    expected = {'labwc', 'LICENSE', 'source.tar.gz', '0001-cancel-super-tap-on-pointer.patch',
                'packages.lock', 'compiler.txt', 'version.txt'}
    if not record or record.get('schema') != 1 or record.get('source') != pin or record.get('files', {}).keys() != expected:
        raise ValueError('Missing pinned Labwc component receipt')
    if record['files']['source.tar.gz'] != pin['sha256'] or record['files']['0001-cancel-super-tap-on-pointer.patch'] != pin['patch_sha256']:
        raise ValueError('Labwc corresponding source differs from pin')
    for name, digest in record['files'].items():
        path = 'usr/bin/labwc' if name == 'labwc' else 'usr/share/licenses/omarchy-labwc/' + name
        mode = 0o755 if name == 'labwc' else 0o644
        if (hashes.get(path), modes.get(path), owners.get(path), groups.get(path)) != (digest, mode, 0, 0):
            raise ValueError('Labwc component content/metadata differs: ' + path)


def verify_bluetooth(record, hashes, modes, owners, groups):
    pin = json.loads((PROJECT / 'desktop/bluetooth/dbus-next.json').read_text())
    if not record or record.get('schema') != 1 or record.get('source') != pin:
        raise ValueError('Missing pinned Bluetooth dependency receipt')
    if not {'lib/dbus_next/__init__.py', 'LICENSE'} <= record.get('files', {}).keys():
        raise ValueError('Incomplete Bluetooth dependency receipt')
    for name, digest in record['files'].items():
        if '..' in PurePosixPath(name).parts or (name != 'LICENSE' and not (name.startswith('lib/dbus_next/') and name.endswith('.py'))):
            raise ValueError('Unsafe Bluetooth dependency path')
        path = ('usr/share/licenses/omarchy-bluetooth-dbus-next/LICENSE' if name == 'LICENSE'
                else 'usr/lib/omarchy-bluetooth/' + name.removeprefix('lib/'))
        if (hashes.get(path), modes.get(path), owners.get(path), groups.get(path)) != (digest, 0o644, 0, 0):
            raise ValueError('Bluetooth dependency content/metadata differs: ' + path)


def verify_tablet_sudo(hashes, modes, owners, groups):
    # sudo asks for the account password, which the installer sets; only the
    # timezone menu's one command runs without it.
    policy = {'etc/sudoers.d/90-tablet': b'tablet ALL=(ALL:ALL) ALL\n',
              'etc/sudoers.d/omarchy-tzupdate': b'tablet ALL=(root) NOPASSWD: /usr/bin/timedatectl set-timezone *\n'}
    for name, data in policy.items():
        expected = hashlib.sha256(data).hexdigest()
        if (hashes.get(name), modes.get(name), owners.get(name), groups.get(name)) != (expected, 0o440, 0, 0):
            raise ValueError('Missing or unsafe tablet sudo policy: ' + name)
    if any(path.startswith('etc/sudoers.d/') and path not in policy for path in hashes):
        raise ValueError('Unexpected sudoers drop-in')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.manifest), indent=2))


if __name__ == '__main__':
    main()
