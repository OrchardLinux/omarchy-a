"""Offline audit of finished assets: namespace safety, integrity and boot contracts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import struct
import tarfile
import zlib

from release import snapshot
from release.manifests import read_release

from .common import PROJECT
from .public_root import sha, check_root_elf
from .recovery_audit import audit_runtime
from release.architecture import validate

# m1n1's payload framing (orchard docs/ram-development.md, "Assembling by hand").
INITRAMFS_MAGIC = b'm1n1_initramfs'
LOGO_MAGIC = b'm1n1_logo_256128'
CASCADE_PADDING = {'loader-padding', 'kernel-padding', 'dtb-padding'}


def dtb_initrd(data):
    """Read /chosen's initrd range from the checked binary tree framing."""
    if len(data) < 40:
        raise ValueError('Truncated Cascadia DTB')
    magic, total, tree, strings, _, version, last, _, names_size, tree_size = struct.unpack_from('>10I', data)
    if (magic != 0xd00dfeed or total != len(data) or version < 17 or last > 17 or
            any(start < 40 or size <= 0 or start + size > total
                for start, size in ((tree, tree_size), (strings, names_size)))):
        raise ValueError('Invalid Cascadia DTB bounds')
    names, end, stack, values, cells, finished = data[strings:strings + names_size], tree + tree_size, [], {}, 2, False
    while tree < end:
        if tree + 4 > end:
            raise ValueError('Truncated Cascadia DTB token')
        token = struct.unpack_from('>I', data, tree)[0]
        tree += 4
        if token == 1:
            stop = data.find(b'\0', tree, end)
            if stop < 0:
                raise ValueError('Unterminated Cascadia DTB node')
            stack.append(data[tree:stop])
            tree = (stop + 4) & ~3
        elif token == 2:
            if not stack:
                raise ValueError('Unbalanced Cascadia DTB')
            stack.pop()
        elif token == 3:
            if not stack or tree + 8 > end:
                raise ValueError('Truncated Cascadia DTB property')
            length, at = struct.unpack_from('>II', data, tree)
            tree += 8
            stop = names.find(b'\0', at)
            if at >= len(names) or stop < 0 or tree + length > end:
                raise ValueError('Invalid Cascadia DTB property')
            name, value = names[at:stop], data[tree:tree + length]
            if stack == [b''] and name == b'#address-cells':
                if len(value) != 4 or (cells := int.from_bytes(value, 'big')) not in (1, 2):
                    raise ValueError('Invalid Cascadia address cells')
            if stack == [b'', b'chosen'] and name in (b'linux,initrd-start', b'linux,initrd-end'):
                if name in values:
                    raise ValueError('Duplicate Cascadia initrd property')
                values[name] = value
            tree = (tree + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack or tree != end:
                raise ValueError('Cascadia DTB ends inside a node')
            finished = True
            break
        else:
            raise ValueError('Unknown Cascadia DTB token')
    if not finished or len(values) != 2 or any(len(value) != cells * 4 for value in values.values()):
        raise ValueError('Cascadia DTB lacks its initrd range')
    return tuple(int.from_bytes(values[key], 'big') for key in (b'linux,initrd-start', b'linux,initrd-end'))


def audit_cascadia(image, parts, receipt):
    required = {'loader', 'kernel', 'dtb', 'initramfs'}
    if (receipt.get('architecture') != 'arm' or receipt.get('initramfs_encoding') != 'cascadia-dtb' or
            set(parts) - CASCADE_PADDING != required):
        raise ValueError('Invalid Cascadia recovery framing')
    loader = parts['loader'][0]
    if loader['offset'] or loader['bytes'] < 0x7f00 + 68 or loader['bytes'] > 0x8000:
        raise ValueError('Invalid Cascadia loader size')
    with image.open('rb') as stream:
        if stream.read(4) != bytes.fromhex('c0000cf1'):
            raise ValueError('Cascadia loader entry differs')
        stream.seek(0x7f00)
        raw = stream.read(68)
        magic, version, size, base, kernel, dtb, dtb_size, initrd, initrd_size, target, image_size, _, _, ram_first, ram_end, limit, crc = struct.unpack('<4s16I', raw)
        if magic != b'CB32' or version != 1 or size != 68 or zlib.crc32(raw[:-4]) != crc:
            raise ValueError('Invalid Cascadia loader configuration')
        if (kernel != 0x8000 or base % 0x8000 or target % 4096 or
                not ram_first <= base < base + image_size <= target < limit <= ram_end or
                target + initrd_size > limit or image_size != image.stat().st_size or
                receipt.get('load_address') != base or receipt.get('kernel_entry') != base + kernel or
                receipt.get('dtb_address') != base + dtb or receipt.get('initramfs_address') != target):
            raise ValueError('Cascadia handoff addresses differ')
        for name, offset, length in (('kernel', kernel, None), ('dtb', dtb, dtb_size), ('initramfs', initrd, initrd_size)):
            row = parts[name][0]
            if row['offset'] != offset or (length is not None and row['bytes'] != length):
                raise ValueError('Cascadia configuration differs from component: ' + name)
        kernel_header = parts['kernel'][1]
        if (len(kernel_header) < 48 or struct.unpack_from('<I', kernel_header, 36)[0] != 0x016f2818 or
                struct.unpack_from('<I', kernel_header, 44)[0] - struct.unpack_from('<I', kernel_header, 40)[0] != parts['kernel'][0]['bytes']):
            raise ValueError('Cascadia kernel is not a complete ARM zImage')
        stream.seek(dtb)
        if dtb_initrd(stream.read(dtb_size)) != (target, target + initrd_size):
            raise ValueError('Cascadia DTB initrd range differs from the loader')
    if not parts['initramfs'][1].startswith(b'\x1f\x8b'):
        raise ValueError('Cascadia initramfs is not gzip-compressed')
    return {'passed': True, 'dtbs': 1, 'initramfs_encoding': 'cascadia-dtb',
            'compressed_bytes': initrd_size, 'initramfs_sha256': parts['initramfs'][0]['sha256']}


def audit_recovery(image, architecture='aarch64'):
    validate(architecture)
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
            if row['name'] in CASCADE_PADDING and any(data):
                raise ValueError('Nonzero recovery padding')
            parts[row['name']] = (row, data[:64])
            end += row['bytes']
    if end != image.stat().st_size or receipt['image_sha256'] != sha(image):
        raise ValueError('Recovery image receipt mismatch')
    if architecture == 'armv7h':
        if dtbs != 1:
            raise ValueError('A Cascadia recovery takes one DTB')
        return audit_cascadia(image, parts, receipt)
    if set(parts) != {'loader', 'logo', 'bootargs', 'dtb', 'kernel', 'initramfs_header', 'initramfs'}:
        raise ValueError('Missing recovery component')
    # The Omarchy mark, which orchard's m1n1 draws only directly after itself.
    if receipt['components'][1]['name'] != 'logo' or not parts['logo'][1].startswith(LOGO_MAGIC):
        raise ValueError('The recovery logo is not m1n1\'s custom logo payload directly after m1n1')
    header = parts['initramfs_header'][1]
    size = parts['initramfs'][0]['bytes']
    if (receipt.get('initramfs_encoding') != 'm1n1_initramfs' or
            header != INITRAMFS_MAGIC + struct.pack('<I', size) or
            not parts['initramfs'][1].startswith(b'\x1f\x8b')):
        raise ValueError('Initramfs is not framed for Linux decompression')
    return {'passed': True, 'dtbs': dtbs, 'initramfs_encoding': receipt['initramfs_encoding'],
            'compressed_bytes': size, 'initramfs_sha256': parts['initramfs'][0]['sha256']}


def private_firmware(orchard=None):
    """Where any board of the orchard snapshot puts its private firmware; none of it may be public."""
    return snapshot.private_firmware(snapshot.directory(orchard))


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


def audit(manifest, orchard=None):
    record = read_release(manifest)
    if record.get('schema') != 2 or record.get('protocol') != 1:
        raise ValueError('Incompatible release manifest')
    private = private_firmware(orchard)
    architecture = record['architecture']
    if architecture == 'aarch64':
        root_receipt = json.loads((Path(manifest).parent / 'rootfs.json').read_text())
        root_path = asset(manifest, {'file': 'rootfs.tar.zst', **{
            key: root_receipt[key] for key in ('bytes', 'sha256')}}, 'root')
        for role, item in (('root image', record['root']), ('root map', record['root']['map']),
                           ('logo', record['logo']), ('pongo', record['pongo']),
                           ('m1n1', record['m1n1']), ('install tools', record['install_tools'])):
            asset(manifest, item, role)
    else:
        root_path = asset(manifest, record['root'], 'root')
    platforms, layers = {}, {}
    for name, files in sorted(record['platforms'].items()):
        layer = audit_layer(asset(manifest, files['layer'], name + ' layer'), name, files['layer'], private)
        if sorted(layer['boards']) != sorted(files['boards']):
            raise ValueError(f'The manifest and the {name} layer list different boards')
        if architecture == 'armv7h':
            image = asset(manifest, files['boot'], name + ' recovery')
            recovery = audit_recovery(image, architecture)
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
                    if data.startswith(b'\x7fELF'):
                        check_root_elf(data, architecture, name)
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
    if 'usr/share/orchard/splash' not in hashes:
        raise ValueError('The root lacks its boot splash for orchard launch')
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
    if cursor.get('architecture') != architecture:
        raise ValueError('Startup cursor helper architecture differs from root')
    if hashes.get('usr/share/licenses/omarchy-wtype/LICENSE') != cursor['files'].get('LICENSE'):
        raise ValueError('Missing startup cursor helper license')
    verify_bluetooth(bluetooth, hashes, modes, owners, groups)
    verify_labwc(labwc, hashes, modes, owners, groups)
    if labwc.get('architecture', 'aarch64') != architecture:
        raise ValueError('Labwc architecture differs from root')
    if 'home/tablet/.local/share/omarchy-ipad/shell/bluetooth-pairing/shell.qml' not in desktop:
        raise ValueError('Pairing UI is absent from desktop integrity manifest')
    for name in ('omarchy-desktop-ready', 'omarchy-wtype', 'omarchy-powerd', 'omarchy-powerctl', 'omarchy-bluetooth-pair'):
        if modes.get('usr/libexec/' + name) != 0o755:
            raise ValueError('Required helper is not executable: ' + name)
    if (links.get('etc/systemd/system/multi-user.target.wants/omarchy-powerd.service') !=
            (True, '/usr/lib/systemd/system/omarchy-powerd.service') or
            'usr/lib/systemd/system/omarchy-powerd.service' not in hashes):
        raise ValueError('Power, lock and sleep have no owner: omarchy-powerd is not enabled')
    if links.get('lib') != (True, 'usr/lib') or owners.get('home/tablet') != 1000 or sizes.get('etc/machine-id') != 0:
        raise ValueError('Invalid root/session contract')
    return {'passed': True, 'hardware_validated': False, 'release': record['release'], 'architecture': architecture,
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
                          '/usr/lib/systemd/system/orchard-usb-network.service',
                      wants + 'sys-subsystem-net-devices-usb0.device.wants/orchard-usb-network.service':
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
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    args = parser.parse_args()
    print(json.dumps(audit(args.manifest, args.orchard), indent=2))


if __name__ == '__main__':
    main()
