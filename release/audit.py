"""Offline audit of finished assets: namespace safety, integrity and boot contracts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import struct
import tarfile

from orchard.image.assemble import INITRAMFS_MAGIC
from release.manifests import read_release

from .common import PROJECT
from .public_root import sha
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


def private_firmware():
    """Where any described board's private firmware lands; none of it may be public."""
    from orchard import hardware
    return {row['destination'] for profile in hardware.profiles()
            for row in json.loads(hardware.firmware_path(profile).read_text())['outputs']}


def asset(manifest, item, role):
    relative = PurePosixPath(item['file'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Asset escapes release directory')
    path = manifest.parent / relative
    if path.is_symlink() or path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
        raise ValueError('Asset integrity mismatch: ' + role)
    return path


def audit_layer(path, platform, row, private):
    """orchard's platform layer: root-owned files under usr/ that say which platform and kernel they are."""
    hashes, expanded = {}, 0
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = member.name
            if (not member.isfile() or not name.startswith('usr/') or '..' in PurePosixPath(name).parts or
                    name in hashes or member.uid or member.gid):
                raise ValueError(f'Unexpected {platform} layer member: {name}')
            if name.removeprefix('usr/') in private:
                raise ValueError('Private firmware found in platform layer')
            data = archive.extractfile(member).read()
            hashes[name] = hashlib.sha256(data).hexdigest()
            expanded += len(data)
            if name == 'usr/lib/orchard/platform.json':
                description = json.loads(data)
            if name == 'usr/lib/orchard/platform.SHA256SUMS':
                sums = data.decode()
    if (len(hashes), expanded) != (row['members'], row['expanded_bytes']):
        raise ValueError(f'The {platform} layer differs from its receipt')
    if (description['platform'], description['kernel_release']) != (platform, row['kernel_release']):
        raise ValueError(f'The {platform} layer describes another platform or kernel')
    release = description['kernel_release']
    if f'usr/lib/modules/{release}/vmlinuz' not in hashes:
        raise ValueError(f'The {platform} layer has no kernel')
    for line in sums.splitlines():
        expected, name = line.split('  ', 1)
        if hashes.get(name.lstrip('/')) != expected:
            raise ValueError(f'The {platform} layer differs from its SHA256SUMS: {name}')
    return {'hashes': hashes, 'boards': description['boards'], 'kernel_release': release}


def audit(manifest):
    record = read_release(manifest)
    if record.get('schema') != 2 or record.get('protocol') != 1:
        raise ValueError('Incompatible release manifest')
    private = private_firmware()
    root_path = asset(manifest, record['root'], 'root')
    asset(manifest, record['pongo'], 'pongo')
    platforms, layers = {}, {}
    for name, files in sorted(record['platforms'].items()):
        layer = audit_layer(asset(manifest, files['layer'], name + ' layer'), name, files['layer'], private)
        if sorted(layer['boards']) != sorted(files['boards']):
            raise ValueError(f'The manifest and the {name} layer list different boards')
        image = asset(manifest, files['boot'], name + ' recovery')
        recovery = audit_recovery(image)
        if recovery['dtbs'] != len(set(layer['boards'].values())):
            raise ValueError(f'The {name} recovery does not start every board of its platform')
        runtime = audit_runtime(image, layer['kernel_release'], record['release'], private)
        # The recovery runs the kernel the installed entry boots: the same modules.
        base = f'usr/lib/modules/{layer["kernel_release"]}/'
        for path, digest in layer['hashes'].items():
            if (path.startswith(base) and path not in (base + 'vmlinuz', base + 'initrd') and
                    not path.startswith(base + 'dtb/') and
                    runtime['hashes'].get(path) != digest):
                raise ValueError(f'The {name} recovery and layer have different modules: {path}')
        recovery['runtime_members_verified'] = runtime['members']
        platforms[name] = {'boards': sorted(layer['boards']), 'kernel_release': layer['kernel_release'],
                           'layer_files': len(layer['hashes']), 'recovery': recovery}
        layers[name] = layer['hashes']
    hashes, links, modes, owners, groups, sizes = {}, {}, {}, {}, {}, {}
    names, ancestors, directories = set(), set(), set()
    desktop = privileges = cursor = bluetooth = labwc = None
    with subprocess.Popen(['zstd', '-d', '-q', '-c', str(root_path)], stdout=subprocess.PIPE) as decoder:
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
    if not desktop:
        raise ValueError('Missing desktop integrity manifest')
    for name, expected in desktop.items():
        if hashes.get(name) != expected:
            raise ValueError('Desktop content mismatch: ' + name)
    for name, layer in layers.items():
        # The installer refuses to write a layer file the root already has.
        clash = sorted((names - directories) & layer.keys())
        if clash:
            raise ValueError(f'The root has files of the {name} layer: ' + ', '.join(clash[:5]))
    verify_tablet_sudo(hashes, modes, owners, groups)
    verify_reachable(hashes, links)
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
            'root_sha256': record['root']['sha256'], 'platforms': platforms,
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


def verify_reachable(hashes, links):
    """Every boot is reachable: a serial console login, SSH and the USB network."""
    wants = 'etc/systemd/system/'
    required_links = {wants + 'getty.target.wants/serial-getty@ttyGS0.service': '/usr/lib/systemd/system/serial-getty@.service',
                      wants + 'multi-user.target.wants/orchard-ssh.service': '/usr/lib/systemd/system/orchard-ssh.service',
                      wants + 'multi-user.target.wants/orchard-usb-network.service':
                          '/usr/lib/systemd/system/orchard-usb-network.service'}
    for name, target in required_links.items():
        if links.get(name) != (True, target):
            raise ValueError('The installed system would not be reachable over USB: ' + name)
    for name in ('usr/bin/dropbear', 'usr/lib/orchard/busybox', 'etc/orchard/udhcpd.conf',
                 'usr/lib/systemd/system/orchard-ssh.service', 'usr/lib/systemd/system/orchard-usb-network.service'):
        if name not in hashes:
            raise ValueError('The installed system would not be reachable over USB: ' + name)


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
