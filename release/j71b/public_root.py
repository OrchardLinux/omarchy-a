"""Build the finished public root before any device operation; no private inputs."""
import argparse
import subprocess
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from .common import group_membership, SYSTEM, NETWORK_RULE
from .runtime import PROJECT, files as runtime_files
from release.package_permissions import privileged_entries, apply as apply_package_permissions


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1048576), b''):
            digest.update(data)
    return digest.hexdigest()


def safe_name(name):
    from pathlib import PurePosixPath
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe public root path')
    return str(path)


def desktop_replacements():
    prefix = 'home/tablet/.local/share/omarchy-ipad/'
    replacements = {prefix + name: (PROJECT / 'desktop/shell' / name).read_bytes() for name in (
        'shell/shell.qml', 'shell/Ui/BarIconButton.qml', 'labwc-rc.xml',
        'shell/plugins/panels/power/Panel.qml', 'shell/plugins/panels/power/Model.js',
        'shell/plugins/panels/bluetooth/Model.js', 'shell/plugins/panels/bluetooth/Panel.qml',
        'bin/omarchy-bluetooth-device')}
    replacements['home/tablet/.config/labwc/rc.xml'] = (PROJECT / 'desktop/shell/labwc-rc.xml').read_bytes()
    replacements['home/tablet/.config/labwc/autostart'] = (PROJECT / 'desktop/configuration/labwc-autostart').read_bytes()
    return replacements


def cursor_files(directory):
    record = json.loads((directory / 'manifest.json').read_text())
    pin = json.loads((PROJECT / 'desktop/cursor/wtype.json').read_text())
    if record.get('schema') != 1 or record.get('architecture') != 'aarch64' or record.get('source') != pin:
        raise ValueError('Incompatible startup cursor helper receipt')
    files = {}
    for name, destination, mode in (
            ('wtype', 'usr/libexec/omarchy-wtype', 0o755),
            ('LICENSE', 'usr/share/licenses/omarchy-wtype/LICENSE', 0o644)):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Invalid startup cursor helper file: ' + name)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record['files'].get(name):
            raise ValueError('Startup cursor helper differs from receipt: ' + name)
        files[destination] = (data, mode)
    files['etc/omarchy/cursor-helper.json'] = (json.dumps(record, sort_keys=True).encode(), 0o644)
    return files


def bluetooth_files(directory):
    record = json.loads((directory / 'manifest.json').read_text())
    pin = json.loads((PROJECT / 'desktop/bluetooth/dbus-next.json').read_text())
    if record.get('schema') != 1 or record.get('source') != pin:
        raise ValueError('Incompatible Bluetooth dependency receipt')
    files = {}
    if not {'lib/dbus_next/__init__.py', 'LICENSE'} <= record['files'].keys():
        raise ValueError('Incomplete Bluetooth dependency receipt')
    for name, digest in record['files'].items():
        if name != 'LICENSE' and not (name.startswith('lib/dbus_next/') and name.endswith('.py')):
            raise ValueError('Unexpected Bluetooth dependency file')
        if safe_name(name) != name:
            raise ValueError('Unsafe Bluetooth dependency path')
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Invalid Bluetooth dependency file')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Bluetooth dependency differs from receipt')
        destination = ('usr/share/licenses/omarchy-bluetooth-dbus-next/LICENSE' if name == 'LICENSE'
                       else 'usr/lib/omarchy-bluetooth/' + name.removeprefix('lib/'))
        files[destination] = (data, 0o644)
    files['etc/omarchy/bluetooth-helper.json'] = (json.dumps(record, sort_keys=True).encode(), 0o644)
    return files


def labwc_files(directory):
    record = json.loads((directory / 'manifest.json').read_text())
    pin = json.loads((PROJECT / 'desktop/labwc/source.json').read_text())
    if record.get('schema') != 1 or record.get('source') != pin:
        raise ValueError('Incompatible Labwc component receipt')
    expected = {'labwc', 'LICENSE', 'source.tar.gz', '0001-cancel-super-tap-on-pointer.patch',
                'packages.lock', 'compiler.txt', 'version.txt'}
    if record.get('files', {}).keys() != expected:
        raise ValueError('Incomplete Labwc component')
    files = {}
    for name, digest in record['files'].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise ValueError('Labwc component differs from receipt')
        destination = 'usr/bin/labwc' if name == 'labwc' else 'usr/share/licenses/omarchy-labwc/' + name
        files[destination] = (path.read_bytes(), 0o755 if name == 'labwc' else 0o644)
    if record['files']['source.tar.gz'] != pin['sha256'] or record['files']['0001-cancel-super-tap-on-pointer.patch'] != pin['patch_sha256']:
        raise ValueError('Labwc corresponding source differs from pin')
    files['etc/omarchy/labwc-helper.json'] = (json.dumps(record, sort_keys=True).encode(), 0o644)
    return files


def desktop_additions():
    name = 'home/tablet/.local/share/omarchy-ipad/shell/bluetooth-pairing/shell.qml'
    return {name: ((PROJECT / 'desktop/shell/shell/bluetooth-pairing/shell.qml').read_bytes(), 0o644)}


def system_files(kernel_release):
    additions = {}
    for path in sorted(SYSTEM.rglob('*')):
        if path.is_file() and not path.is_symlink():
            name = path.relative_to(SYSTEM).as_posix()
            data = path.read_bytes().replace(b'@KERNEL_RELEASE@', kernel_release.encode())
            mode = 0o440 if name.startswith('etc/sudoers.d/') else (
                0o755 if name.startswith('usr/libexec/') else 0o644)
            additions[name] = (data, mode)
    return additions


def boot_files(kernel, dtb, kernel_release):
    """The kernel and DTB where kernel-install finds them (hardware docs/boot-contract.md).

    kernel-install copies both to the boot partition and writes the BLS entry;
    /etc/kernel/devicetree names the board's DTB. mkinitcpio builds the initrd.
    """
    import orchard_hardware
    name = orchard_hardware.device('j71b')['kernel']['dtb'] + '.dtb'
    base = f'usr/lib/modules/{kernel_release}/'
    return {base + 'vmlinuz': (kernel.read_bytes(), 0o644),
            base + 'dtb/' + name: (dtb.read_bytes(), 0o644),
            'etc/kernel/devicetree': (name.encode() + b'\n', 0o644)}


def build(base, base_receipt, modules_dir, outdir, release, cursor_tools, bluetooth_tools=None,
          labwc_tools=None, *, kernel, dtb):
    if outdir.exists():
        raise ValueError('Choose a new release output directory')
    record = json.loads(base_receipt.read_text())
    if base.is_symlink() or base.stat().st_size != record['bytes'] or sha(base) != record['sha256']:
        raise ValueError('Base root differs from receipt')
    privileges = privileged_entries(base)
    privileged_digests = {}
    kernel_release, additions = runtime_files(modules_dir)
    additions.update(cursor_files(cursor_tools))
    additions.update(bluetooth_files(bluetooth_tools or PROJECT / 'out/desktop/bluetooth-tools'))
    additions.update(labwc_files(labwc_tools or PROJECT / 'out/desktop/labwc-tools'))
    desktop_extra = desktop_additions()
    additions.update(desktop_extra)
    additions['etc/omarchy/package-privileges.json'] = (json.dumps(privileges, sort_keys=True).encode(), 0o644)
    additions.update(system_files(kernel_release))
    additions.update(boot_files(kernel, dtb, kernel_release))
    additions['etc/polkit-1/rules.d/60-j71b-tablet-network.rules'] = (NETWORK_RULE.read_bytes(), 0o644)
    additions['etc/orchard/release.json'] = (json.dumps({
        'protocol': 1, 'release': release, 'profile': 'j71b', 'kernel_release': kernel_release}).encode(), 0o644)
    if privileges.keys() & additions.keys():
        raise ValueError('Runtime must not override privileged package files')
    qml_path = 'home/tablet/.local/share/omarchy-ipad/shell/shell.qml'
    replacements = desktop_replacements()
    outdir.parent.mkdir(parents=True, exist_ok=True)
    seen, directories, expanded, count = set(), set(), 0, 0
    with tempfile.TemporaryDirectory(dir=outdir.parent, prefix='.root-') as temp:
        temporary = Path(temp)
        archive = temporary / 'rootfs.tar.zst'
        with archive.open('wb') as raw, subprocess.Popen(
                ['zstd', '-T0', '-1', '--check', '-q', '-c'], stdin=subprocess.PIPE, stdout=raw) as compressor:
            with tarfile.open(fileobj=compressor.stdin, mode='w|') as target:
                def add(member, data=None):
                    nonlocal expanded, count
                    if member.name in seen:
                        raise ValueError('Root collision: ' + member.name)
                    seen.add(member.name)
                    if member.isdir():
                        directories.add(member.name)
                    expanded += member.size
                    count += 1
                    target.addfile(member, io.BytesIO(data) if data is not None else None)

                with tarfile.open(base, 'r|gz') as source:
                    for member in source:
                        if member.name in ('.', './'):
                            continue
                        member.name = safe_name(member.name)
                        # Stale PAX path/size fields override the normalized header.
                        member.pax_headers = {key: value for key, value in member.pax_headers.items()
                                              if key not in ('path', 'size')}
                        if member.name in additions:
                            continue
                        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                            raise ValueError('Special member in base root')
                        if member.name == 'lib' and (not member.issym() or member.linkname != 'usr/lib'):
                            raise ValueError('Base must link lib to usr/lib')
                        data = source.extractfile(member).read() if member.isfile() else None
                        if member.name in ('etc/group', 'etc/gshadow'):
                            data = group_membership(data, shadow=member.name == 'etc/gshadow')
                        if member.name in replacements:
                            data = replacements[member.name]
                        if member.name == 'arch-ipad-ui-manifest.json':
                            manifest = json.loads(data)
                            for name, replacement in replacements.items():
                                if name not in manifest:
                                    raise ValueError('Desktop replacement is absent from base manifest: ' + name)
                                manifest[name] = hashlib.sha256(replacement).hexdigest()
                            for name, (content, mode) in desktop_extra.items():
                                manifest[name] = hashlib.sha256(content).hexdigest()
                            data = (json.dumps(manifest, indent=2) + '\n').encode()
                        if data is not None:
                            member.size = len(data)
                        if member.name in privileges:
                            apply_package_permissions(member, data, privileges[member.name], privileged_digests)
                        add(member, data)
                def add_parents(name):
                    for parent in reversed(PurePosixPath(name).parents):
                        parent = str(parent)
                        if parent == '.':
                            continue
                        if parent in seen:
                            if parent not in directories:
                                raise ValueError('Runtime parent is not a directory: ' + parent)
                            continue
                        member = tarfile.TarInfo(parent)
                        member.type, member.mode = tarfile.DIRTYPE, 0o755
                        add(member)

                for name, (data, mode) in sorted(additions.items()):
                    add_parents(name)
                    member = tarfile.TarInfo(name)
                    member.mode, member.size = mode, len(data)
                    add(member, data)
                for unit in ('omarchy-pacman-init.service',):
                    member = tarfile.TarInfo('etc/systemd/system/multi-user.target.wants/' + unit)
                    member.type, member.linkname, member.mode = tarfile.SYMTYPE, '/usr/lib/systemd/system/' + unit, 0o777
                    if member.name not in seen:
                        add_parents(member.name)
                        add(member)
            compressor.stdin.close()
            if compressor.wait():
                raise ValueError('Public root compression failed')
        required = {'lib', 'usr/lib/systemd/systemd', 'etc/group', 'etc/gshadow', qml_path,
                    'arch-ipad-ui-manifest.json'}
        if not required <= seen or not privileges.keys() <= seen or not replacements.keys() <= seen:
            raise ValueError('Incomplete public root or privileged package metadata')
        receipt = {'schema': 1, 'kind': 'rootfs', 'profile': 'j71b', 'release': release,
                   'bytes': archive.stat().st_size, 'sha256': sha(archive), 'compression': 'zstd',
                   'expanded_bytes': expanded, 'members': count, 'kernel_release': kernel_release,
                   'base_sha256': record['sha256']}
        (temporary / 'rootfs.json').write_text(json.dumps(receipt, indent=2) + '\n')
        os.replace(temporary, outdir)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'base-receipt', 'modules-dir', 'outdir', 'cursor-tools', 'bluetooth-tools', 'labwc-tools'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.base_receipt, args.modules_dir, args.outdir, args.release, args.cursor_tools, args.bluetooth_tools, args.labwc_tools), indent=2))


if __name__ == '__main__':
    main()
