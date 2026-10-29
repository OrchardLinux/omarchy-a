"""Compose the native Omarchy A N61 desktop root for a private NFS session."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile

from release import desktop
from release.package_permissions import privileged_entries, apply as apply_privileges
from orchard_cli import provenance
from .common import ARCHITECTURE, KERNEL_RELEASE, PROFILE, PROJECT, encoded, member_record, name, sha


def kernel_component(modules_dir):
    """Validate the hardware producer's complete, device-specific output."""
    modules_dir = Path(modules_dir)
    kernel = modules_dir.parent.parent
    if (modules_dir.is_symlink() or kernel.is_symlink() or
            not modules_dir.is_dir() or not kernel.is_dir()):
        raise ValueError('Expected a regular N61 kernel component')
    receipt_path = kernel / 'receipt.json'
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise ValueError('N61 kernel component receipt is required')
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get('schema'), receipt.get('device'), receipt.get('platform'),
            receipt.get('dtb'), receipt.get('kernel_release')) != (
            1, PROFILE, 'apple-4k', 't7000-n61', KERNEL_RELEASE):
        raise ValueError('N61 kernel component identity differs')
    source = receipt.get('source')
    if (not isinstance(source, dict) or any(
            not isinstance(source.get(key), str) or not re.fullmatch('[0-9a-f]{40}', source[key])
            for key in ('commit', 'tree', 'prepared_tree')) or any(
            not isinstance(source.get(key), str) or not re.fullmatch('[0-9a-f]{64}', source[key])
            for key in ('patch_list_sha256', 'config_sha256'))):
        raise ValueError('N61 kernel source receipt is incomplete')
    recipe = receipt.get('hardware_recipe')
    if not isinstance(recipe, dict) or not isinstance(recipe.get('files'), dict):
        raise ValueError('N61 hardware recipe snapshot is missing')
    recipe_bytes = json.dumps(recipe['files'], sort_keys=True, separators=(',', ':')).encode()
    if (recipe.get('sha256') != hashlib.sha256(recipe_bytes).hexdigest() or
            not {'devices/n61/device.toml', 'devices/n61/firmware.json',
                 'kernel/configs/apple-4k/config'} <= recipe['files'].keys()):
        raise ValueError('N61 hardware recipe snapshot differs')
    releases = [p for p in modules_dir.iterdir() if p.is_dir() and not p.is_symlink()]
    if (len(releases) != 1 or releases[0].name != KERNEL_RELEASE or
            (kernel / 'kernel.release').read_text().strip() != KERNEL_RELEASE):
        raise ValueError('Expected the matching N61 4K kernel module tree')
    tree = releases[0]
    records = receipt.get('files')
    if not isinstance(records, dict):
        raise ValueError('N61 kernel component inventory is missing')
    required = {'Image.gz', 'n61.dtb', 'dtbs/t7000-n61.dtb', 'kernel.release',
                'lib/modules/' + KERNEL_RELEASE + '/modules.dep'}
    if not required <= records.keys():
        raise ValueError('N61 kernel component is incomplete')
    actual = set()
    for path in kernel.rglob('*'):
        if path.is_symlink():
            raise ValueError('Linked kernel component inputs are unsupported')
        if path.is_file() and path != receipt_path:
            actual.add(path.relative_to(kernel).as_posix())
        elif not path.is_file() and not path.is_dir():
            raise ValueError('Unsupported kernel component input')
    if actual != records.keys():
        raise ValueError('N61 kernel component inventory differs')
    for key, item in records.items():
        if (name(key) != key or not isinstance(item, dict) or
                set(item) != {'bytes', 'sha256'} or type(item['bytes']) is not int or
                not isinstance(item['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('Invalid N61 kernel component inventory entry')
        path = kernel / key
        if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ValueError('N61 kernel component differs: ' + key)
    if records['n61.dtb'] != records['dtbs/t7000-n61.dtb']:
        raise ValueError('N61 selected device tree differs')
    modules = list(tree.rglob('*.ko'))
    if not modules:
        raise ValueError('N61 kernel module tree is empty')
    for path in modules:
        data = path.read_bytes()
        if (data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\xb7\0' or
                b'vermagic=' + KERNEL_RELEASE.encode() + b' ' not in data):
            raise ValueError('N61 module architecture or release differs: ' + path.name)
    return receipt, sha(receipt_path)


def hardware_evidence(receipt, hardware=None):
    if hardware is None:
        import orchard_hardware
        hardware = Path(orchard_hardware.__file__).resolve().parent
    hardware = Path(hardware)
    if hardware.is_symlink() or not hardware.is_dir():
        raise ValueError('Expected a hardware package or checkout')
    hardware = hardware.resolve()
    for key, expected in receipt['hardware_recipe']['files'].items():
        if name(key) != key or not isinstance(expected, dict):
            raise ValueError('Invalid hardware recipe snapshot entry')
        path = hardware
        for part in PurePosixPath(key).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError('Linked hardware recipe input: ' + key)
        if (not path.is_file() or path.stat().st_size != expected.get('bytes') or
                sha(path) != expected.get('sha256')):
            raise ValueError('Hardware package differs from the kernel recipe: ' + key)
    return provenance.snapshot(hardware)


def additions(modules_dir, cursor_tools, bluetooth_tools, labwc_tools):
    modules_dir = Path(modules_dir)
    tree = modules_dir / KERNEL_RELEASE
    files = {}
    for path in sorted(tree.rglob('*')):
        if path.is_symlink():
            raise ValueError('Linked kernel module inputs are unsupported')
        if path.is_file():
            files['usr/lib/modules/' + KERNEL_RELEASE + '/' + path.relative_to(tree).as_posix()] = (path.read_bytes(), 0o644)
    files.update(desktop.cursor_files(Path(cursor_tools), PROJECT))
    files.update(desktop.bluetooth_files(Path(bluetooth_tools), PROJECT))
    files.update(desktop.labwc_files(Path(labwc_tools), PROJECT))
    overlay = PROJECT / 'system/n61/overlay'
    for path in sorted(overlay.rglob('*')):
        if path.is_symlink():
            raise ValueError('N61 policy must contain regular source files')
        if path.is_file():
            key = path.relative_to(overlay).as_posix()
            mode = 0o440 if key.startswith('etc/sudoers.d/') else (
                0o755 if key.startswith(('usr/libexec/', 'usr/local/libexec/')) else 0o644)
            files[key] = (path.read_bytes(), mode)
    # Use the same upstream helpers as the other AArch64 desktop profile.
    shared = PROJECT / 'system/j71b/overlay'
    for key, mode in (('usr/libexec/omarchy-screen-toggle', 0o755),
                      ('usr/lib/systemd/system/omarchy-pacman-init.service', 0o644)):
        source = shared / key
        if source.is_symlink() or not source.is_file():
            raise ValueError('Shared desktop helper is missing: ' + key)
        files[key] = (source.read_bytes(), mode)
    files['usr/lib/omarchy/image_policy.py'] = ((PROJECT / 'image/n61/image_policy.py').read_bytes(), 0o644)
    files['usr/libexec/omarchy-desktop-ready'] = ((PROJECT / 'desktop/configuration/desktop-ready').read_bytes(), 0o755)
    brightness = 'home/tablet/.local/share/omarchy-ipad/bin/omarchy-brightness-display'
    files[brightness] = ((PROJECT / 'desktop/shell/bin/omarchy-brightness-display').read_bytes(), 0o755)
    session = (PROJECT / 'desktop/configuration/login-session').read_bytes()
    entry = b'exec /usr/bin/labwc\n'
    if session.count(entry) != 1:
        raise ValueError('The shared desktop session entrypoint changed')
    files['usr/local/libexec/arch-ipad-login-session'] = (
        session.replace(entry, b'export WLR_LIBINPUT_NO_DEVICES=1\n' + entry), 0o755)
    return files


def build(base, modules_dir, cursor_tools, bluetooth_tools, labwc_tools, output, *, release=None, hardware=None):
    base, output = Path(base), Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Choose a new N61 release directory')
    receipt = json.loads((base / 'rootfs.tar.gz.json').read_text())
    if (receipt.get('kind'), receipt.get('profile'), receipt.get('architecture')) != ('omarchy-a.base', PROFILE, ARCHITECTURE):
        raise ValueError('Expected a native N61 AArch64 base receipt')
    archive = base / 'rootfs.tar.gz'
    if archive.is_symlink() or archive.stat().st_size != receipt['bytes'] or sha(archive) != receipt['sha256']:
        raise ValueError('N61 base differs from its receipt')
    if sha(base / 'packages.lock') != receipt['packages_lock_sha256']:
        raise ValueError('N61 package inventory differs from its receipt')
    release = receipt['release'] if release is None else release
    if not isinstance(release, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._+-]{0,127}', release):
        raise ValueError('Invalid N61 release name')
    kernel_receipt, kernel_receipt_sha = kernel_component(modules_dir)
    hardware_source = hardware_evidence(kernel_receipt, hardware)
    cli_source = provenance.cli()
    files = additions(modules_dir, cursor_tools, bluetooth_tools, labwc_tools)
    privileges = privileged_entries(archive)
    if files.keys() & privileges.keys():
        raise ValueError('N61 policy cannot replace privileged package files')
    files['etc/omarchy/package-privileges.json'] = (encoded(privileges), 0o644)
    files['etc/orchard/release.json'] = (encoded({
        'schema': 1, 'distro': 'omarchy-a', 'profile': PROFILE, 'architecture': ARCHITECTURE,
        'release': release, 'kernel_release': KERNEL_RELEASE}), 0o644)
    catalog, privileged_digests = {}, {}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.n61-root-', dir=output.parent) as directory:
        work = Path(directory)
        root_archive = work / 'rootfs.tar.gz'
        with root_archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0, compresslevel=1) as zipped:
            with tarfile.open(fileobj=zipped, mode='w|') as target:
                def add(member, data=None):
                    member.name = name(member.name)
                    if member.name in catalog:
                        raise ValueError('Duplicate N61 root member: ' + member.name)
                    member.pax_headers = {k: v for k, v in member.pax_headers.items() if k not in ('path', 'size')}
                    catalog[member.name] = member_record(member, data)
                    target.addfile(member, io.BytesIO(data) if data is not None else None)

                with tarfile.open(archive, 'r|gz') as source:
                    for member in source:
                        if member.name in ('.', './'):
                            continue
                        member.name = name(member.name)
                        if member.name in files:
                            continue
                        data = source.extractfile(member).read() if member.isfile() else None
                        if member.name == 'arch-ipad-ui-manifest.json':
                            ui = json.loads(data)
                            brightness = 'home/tablet/.local/share/omarchy-ipad/bin/omarchy-brightness-display'
                            if brightness not in ui:
                                raise ValueError('Desktop manifest lacks the brightness helper')
                            for key, (content, _) in files.items():
                                if key in ui:
                                    ui[key] = hashlib.sha256(content).hexdigest()
                            data = encoded(ui)
                        if data is not None:
                            member.size = len(data)
                        if member.name in privileges:
                            apply_privileges(member, data, privileges[member.name], privileged_digests)
                        add(member, data)
                def parents(key):
                    for parent in reversed(PurePosixPath(key).parents):
                        parent = str(parent)
                        if parent == '.':
                            continue
                        if parent in catalog:
                            if catalog[parent]['type'] != 'directory':
                                raise ValueError('N61 policy parent is not a directory: ' + parent)
                            continue
                        member = tarfile.TarInfo(parent)
                        member.type, member.mode = tarfile.DIRTYPE, 0o755
                        add(member)
                for key, (data, mode) in sorted(files.items()):
                    parents(key)
                    member = tarfile.TarInfo(key)
                    member.mode, member.size = mode, len(data)
                    if key.startswith('home/tablet/'):
                        member.uid = member.gid = 1000
                    add(member, data)
                for target_unit, unit in (('swap.target', 'omarchy-zram.service'),
                                          ('multi-user.target', 'omarchy-pacman-init.service')):
                    key = 'etc/systemd/system/' + target_unit + '.wants/' + unit
                    parents(key)
                    member = tarfile.TarInfo(key)
                    member.type, member.mode = tarfile.SYMTYPE, 0o777
                    member.linkname = '/usr/lib/systemd/system/' + unit
                    add(member)
        (work / 'packages.lock').write_bytes((base / 'packages.lock').read_bytes())
        kernel_receipt_file = Path(modules_dir).parent.parent / 'receipt.json'
        (work / 'kernel.json').write_bytes(kernel_receipt_file.read_bytes())
        if sha(work / 'kernel.json') != kernel_receipt_sha:
            raise ValueError('N61 kernel receipt changed during packaging')
        (work / 'rootfs.catalog.json').write_bytes(encoded(catalog))
        record = {'schema': 1, 'kind': 'omarchy-a.nfs-root', 'distro': 'omarchy-a',
                  'profile': PROFILE, 'architecture': ARCHITECTURE, 'release': release,
                  'base_release': receipt['release'], 'producer': {'cli': cli_source, 'hardware': hardware_source},
                  'qualification': 'pending-physical-desktop-boot', 'kernel_release': KERNEL_RELEASE,
                  'kernel': {'receipt_sha256': kernel_receipt_sha, 'source': kernel_receipt['source'],
                             'hardware_recipe_sha256': kernel_receipt['hardware_recipe']['sha256'],
                             'image_sha256': kernel_receipt['files']['Image.gz']['sha256'],
                             'dtb_sha256': kernel_receipt['files']['n61.dtb']['sha256']},
                  'runtime': 'n61-systemd-nfs-v1', 'base_sha256': receipt['sha256'],
                  'root': {'file': 'rootfs.tar.gz', 'compression': 'gzip', 'bytes': root_archive.stat().st_size,
                           'sha256': sha(root_archive), 'members': len(catalog),
                           'expanded_bytes': sum(row.get('bytes', 0) for row in catalog.values())},
                  'catalog_sha256': sha(work / 'rootfs.catalog.json'),
                  'packages_lock_sha256': sha(work / 'packages.lock'),
                  'desktop': {'compositor': 'labwc', 'renderer': 'pixman', 'qtquick': 'software',
                              'panel': [750, 1334], 'scale': 1.5, 'zram_max_bytes': 536870912}}
        (work / 'rootfs.json').write_bytes(encoded(record))
        from .audit import audit
        audit(work)
        os.replace(work, output)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('base', 'modules-dir', 'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--release', help='name for the assembled release; defaults to the base release')
    parser.add_argument('--hardware', type=Path, help='matching hardware package or checkout')
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.modules_dir, args.cursor_tools, args.bluetooth_tools,
                           args.labwc_tools, args.output, release=args.release, hardware=args.hardware), indent=2))


if __name__ == '__main__':
    main()
