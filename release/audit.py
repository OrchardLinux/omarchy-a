"""Offline audit of finished assets: namespace safety, integrity and boot contracts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

import gzip

from release import snapshot
from release.architecture import validate, check_elf
from release.package_permissions import parse_mtree
from release.manifests import read_release

from .public_root import sha

# The two compiled helpers of the omarchy-a package, of the root's architecture.
HELPERS = {'usr/libexec/omarchy-wtype': 'startup cursor helper',
           'usr/share/omarchy/trials/wvkbd-mobintl-v0.20-font18-special15-state': 'on-screen keyboard'}

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
    # The checks read the tree the image was made from; orchard.image.root_image made it, and checks it.
    root_receipt = json.loads((Path(manifest).parent / 'rootfs.json').read_text())
    architecture = validate(root_receipt.get('architecture', 'aarch64'))
    root_path = asset(manifest, {'file': 'rootfs.tar.zst', **{key: value for key, value in root_receipt.items()
                                                              if key in ('bytes', 'sha256')}}, 'root')
    if architecture == 'aarch64' and not ({'pongo', 'm1n1'} <= record['loaders'].keys() and record['logo']):
        raise ValueError('An arm64 release boots with orchard\'s Pongo and m1n1, and has a logo')
    if architecture == 'armv7h' and (record['boot_method'] != 'recovery-autogo' or record['logo'] or
                                     not all(name.startswith('cascadia ') for name in record['loaders'])):
        raise ValueError('A 32-bit release boots with each board\'s Cascadia loader, and has no logo')
    for role, item in (('root image', record['root']), ('root map', record['root']['map']),
                       *((('logo', record['logo']),) if record['logo'] else ()),
                       *record['loaders'].items(), ('install tools', record['install_tools'])):
        asset(manifest, item, role)
    platforms, layers = {}, {}
    for name, files in sorted(record['platforms'].items()):
        layer = audit_layer(asset(manifest, files['layer'], name + ' layer'), name, files['layer'], private)
        if sorted(layer['boards']) != sorted(files['boards']):
            raise ValueError(f'The manifest and the {name} layer list different boards')
        platforms[name] = {'boards': sorted(layer['boards']), 'kernel_release': layer['kernel_release'],
                           'layer_files': len(layer['hashes'])}
        layers[name] = layer['hashes']
    hashes, links, modes, owners, groups, sizes = {}, {}, {}, {}, {}, {}
    names, ancestors, directories = set(), set(), set()
    desktop, desktop_package = None, None
    privileges = None
    headers = {}
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
                    # This repository's package, as pacman installed it.
                    if name.startswith('var/lib/pacman/local/omarchy-a-') and name.endswith('/mtree'):
                        if desktop is not None:
                            raise ValueError('Two omarchy-a packages in the root')
                        desktop_package = PurePosixPath(name).parent.name
                        desktop = dict(parse_mtree((gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data).decode(),
                                                   every=True))
                    if name in HELPERS:
                        headers[name] = data[:64]
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
        raise ValueError('The root has no omarchy-a package')
    verify_package(desktop, hashes, links, modes, owners, directories)
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
    # The helpers built for the desktop are of the root's architecture.
    for name, label in HELPERS.items():
        if name not in headers:
            raise ValueError('The root lacks the ' + label)
        check_elf(headers[name], architecture, label)
    if 'usr/share/licenses/omarchy-wtype/LICENSE' not in hashes:
        raise ValueError('Missing startup cursor helper license')
    verify_bluetooth(hashes, modes, owners, groups)
    if 'usr/share/omarchy/shell/bluetooth-pairing/shell.qml' not in desktop:
        raise ValueError('Pairing UI is absent from the omarchy-a package')
    verify_package_setup(desktop, hashes)
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
            'members': len(names), 'desktop_package': desktop_package, 'desktop_files_verified': len(desktop),
            'root_sha256': record['root']['sha256'], 'platforms': platforms,
            'privileged_entries_verified': len(privileges)}


def verify_package(entries, hashes, links, modes, owners, directories):
    """Every file and link of the omarchy-a package is in the root as pacman recorded it."""
    for name, entry in entries.items():
        if entry['type'] == 'file':
            if (hashes.get(name) != entry['sha256'] or modes.get(name, 0) & 0o7777 != entry['mode'] or
                    owners.get(name) != entry['uid']):
                raise ValueError('The root differs from the omarchy-a package: ' + name)
        elif entry['type'] == 'link':
            if links.get(name) != (True, entry['link']):
                raise ValueError('The root differs from the omarchy-a package: ' + name)
        elif entry['type'] == 'dir':
            if name not in directories:
                raise ValueError('The root lacks a directory of the omarchy-a package: ' + name)
        else:
            raise ValueError('Unexpected omarchy-a package entry: ' + name)


def verify_package_setup(entries, hashes):
    """What the package's install did: its versions of other packages' files are in place, and the
    tablet user, made from /etc/skel, has every migration it ships marked done."""
    overrides = 'usr/share/omarchy/etc-overrides/'
    markers = 'etc/skel/.local/state/omarchy/migrations/'
    for name, entry in entries.items():
        if name.startswith(overrides) and entry['type'] == 'file':
            if hashes.get(name.removeprefix(overrides)) != entry['sha256']:
                raise ValueError('The package hook did not put its file in place: /' + name.removeprefix(overrides))
        if name.startswith(markers) and entry['type'] == 'file':
            if 'home/tablet/.local/state/omarchy/migrations/' + name.removeprefix(markers) not in hashes:
                raise ValueError('The tablet user would run a migration meant for older installs: ' + name)
    migrations = {name.removeprefix('usr/share/omarchy/migrations/') for name in entries
                  if name.startswith('usr/share/omarchy/migrations/') and name.endswith('.sh')}
    marked = {name.removeprefix(markers) for name in entries if name.startswith(markers)} - {''}
    if migrations != marked:
        raise ValueError('/etc/skel does not mark exactly the package\'s migrations as done')


def verify_bluetooth(hashes, modes, owners, groups):
    """The Bluetooth helper's D-Bus library, root's and readable by all."""
    library = [name for name in hashes if name.startswith('usr/lib/omarchy-bluetooth/dbus_next/')]
    for name in ('usr/lib/omarchy-bluetooth/dbus_next/__init__.py',
                 'usr/share/licenses/omarchy-bluetooth-dbus-next/LICENSE'):
        if name not in hashes:
            raise ValueError('Missing Bluetooth dependency file: ' + name)
    for name in library + ['usr/share/licenses/omarchy-bluetooth-dbus-next/LICENSE']:
        if (modes.get(name), owners.get(name), groups.get(name)) != (0o644, 0, 0):
            raise ValueError('Bluetooth dependency metadata differs: ' + name)


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
