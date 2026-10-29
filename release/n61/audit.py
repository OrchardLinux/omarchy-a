"""Audit an N61 NFS desktop artifact before private staging."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from .common import ARCHITECTURE, KERNEL_RELEASE, PROFILE, aarch64, member_record, name, sha


def audit(directory):
    directory = Path(directory)
    receipt = json.loads((directory / 'rootfs.json').read_text())
    if (receipt.get('schema'), receipt.get('kind'), receipt.get('profile'), receipt.get('architecture'),
            receipt.get('kernel_release')) != (1, 'omarchy-a.nfs-root', PROFILE, ARCHITECTURE, KERNEL_RELEASE):
        raise ValueError('Expected the N61 AArch64 NFS root contract')
    if receipt['root']['file'] != 'rootfs.tar.gz' or receipt['root']['compression'] != 'gzip':
        raise ValueError('Unexpected N61 root archive')
    archive = directory / 'rootfs.tar.gz'
    if archive.is_symlink() or archive.stat().st_size != receipt['root']['bytes'] or sha(archive) != receipt['root']['sha256']:
        raise ValueError('N61 root stream differs from its receipt')
    for key, digest in (('rootfs.catalog.json', receipt['catalog_sha256']), ('packages.lock', receipt['packages_lock_sha256'])):
        if sha(directory / key) != digest:
            raise ValueError('N61 release metadata differs: ' + key)
    kernel = receipt.get('kernel', {})
    producer = receipt.get('producer', {})
    if (not isinstance(producer, dict) or not isinstance(producer.get('cli'), dict) or
            not isinstance(producer.get('hardware'), dict) or
            not isinstance(producer['hardware'].get('sha256'), str)):
        raise ValueError('N61 producer provenance is missing')
    kernel_path = directory / 'kernel.json'
    if (not isinstance(kernel, dict) or kernel_path.is_symlink() or
            not kernel_path.is_file() or sha(kernel_path) != kernel.get('receipt_sha256')):
        raise ValueError('N61 kernel receipt differs')
    kernel_receipt = json.loads(kernel_path.read_text())
    if (kernel_receipt.get('schema'), kernel_receipt.get('device'), kernel_receipt.get('platform'),
            kernel_receipt.get('dtb'), kernel_receipt.get('kernel_release')) != (
            1, PROFILE, 'apple-4k', 't7000-n61', KERNEL_RELEASE):
        raise ValueError('N61 kernel receipt identity differs')
    kernel_files = kernel_receipt.get('files', {})
    recipe = kernel_receipt.get('hardware_recipe', {})
    if (not isinstance(kernel_files, dict) or kernel.get('source') != kernel_receipt.get('source') or
            not isinstance(recipe, dict) or not isinstance(recipe.get('files'), dict) or
            kernel.get('hardware_recipe_sha256') != recipe.get('sha256') or
            recipe.get('sha256') != hashlib.sha256(json.dumps(
                recipe['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest() or
            kernel.get('image_sha256') != kernel_files.get('Image.gz', {}).get('sha256') or
            kernel.get('dtb_sha256') != kernel_files.get('n61.dtb', {}).get('sha256')):
        raise ValueError('N61 kernel receipt does not match release metadata')
    expected = json.loads((directory / 'rootfs.catalog.json').read_text())
    actual, contents = {}, {}
    selected = {'usr/lib/systemd/systemd', 'usr/bin/sudo', 'etc/orchard/release.json',
                'usr/local/libexec/arch-ipad-login-session', 'usr/libexec/omarchy-desktop-ready',
                'usr/libexec/omarchy-screen-toggle', 'usr/lib/systemd/system/omarchy-pacman-init.service',
                'home/tablet/.local/share/omarchy-ipad/bin/omarchy-brightness-display', 'arch-ipad-ui-manifest.json',
                'home/tablet/.config/labwc/autostart', 'home/tablet/.local/share/omarchy-ipad/shell/shell.qml',
                'etc/sudoers.d/90-tablet-passwordless', 'etc/omarchy/package-privileges.json'}
    with tarfile.open(archive, 'r|gz') as stream:
        for member in stream:
            key = name(member.name)
            if key in actual:
                raise ValueError('Duplicate N61 archive member')
            if (key.startswith('usr/libexec/orchard-j71b/') or key == 'etc/orchard/nfs-root.json' or
                    key == 'etc/orchard/firmware.json' or key.endswith('/authorized_keys') or
                    key.startswith('etc/ssh/ssh_host_')):
                raise ValueError('Unexpected board runtime or private session data: ' + key)
            data = stream.extractfile(member).read() if member.isfile() else None
            member.name = key
            actual[key] = member_record(member, data)
            if key in selected:
                contents[key] = data
    if actual != expected or len(actual) != receipt['root']['members']:
        raise ValueError('N61 archive inventory differs from its receipt')
    if not selected <= actual.keys() or not aarch64(contents['usr/lib/systemd/systemd']):
        raise ValueError('Incomplete AArch64 Omarchy desktop root')
    for key in actual:
        for parent in PurePosixPath(key).parents:
            if str(parent) in actual and actual[str(parent)]['type'] != 'directory':
                raise ValueError('N61 archive traverses a guest link')
    sudo = actual['usr/bin/sudo']
    if (sudo['uid'], sudo['gid'], sudo['mode']) != (0, 0, 0o4755):
        raise ValueError('N61 sudo privilege contract differs')
    if contents['etc/sudoers.d/90-tablet-passwordless'] != b'tablet ALL=(ALL:ALL) NOPASSWD: ALL\n':
        raise ValueError('N61 tablet sudo policy differs')
    policy = json.loads(contents['etc/orchard/release.json'])
    if (policy['profile'], policy['architecture'], policy['kernel_release'], policy['release']) != (
            PROFILE, ARCHITECTURE, KERNEL_RELEASE, receipt['release']):
        raise ValueError('N61 root policy differs from its receipt')
    login = contents['usr/local/libexec/arch-ipad-login-session']
    for setting in (b'WLR_RENDERER=pixman', b'QT_QUICK_BACKEND=software', b'LIBGL_ALWAYS_SOFTWARE=1',
                    b'WLR_LIBINPUT_NO_DEVICES=1'):
        if setting not in login:
            raise ValueError('N61 software desktop policy is missing')
    if 'usr/lib/modules/' + KERNEL_RELEASE + '/modules.dep' not in actual:
        raise ValueError('N61 matching module tree is missing')
    prefix = 'lib/modules/' + KERNEL_RELEASE + '/'
    expected_modules = {'usr/' + key: item for key, item in kernel_files.items() if key.startswith(prefix)}
    actual_modules = {key: item for key, item in actual.items()
                      if key.startswith('usr/' + prefix) and item['type'] == 'file'}
    if (not expected_modules or actual_modules.keys() != expected_modules.keys() or any(
            (actual_modules[key]['bytes'], actual_modules[key]['sha256']) !=
            (item.get('bytes'), item.get('sha256')) for key, item in expected_modules.items())):
        raise ValueError('N61 modules differ from the kernel receipt')
    if actual['usr/libexec/omarchy-screen-toggle']['mode'] != 0o755:
        raise ValueError('N61 screen toggle is not executable')
    brightness = 'home/tablet/.local/share/omarchy-ipad/bin/omarchy-brightness-display'
    if json.loads(contents['arch-ipad-ui-manifest.json']).get(brightness) != hashlib.sha256(contents[brightness]).hexdigest():
        raise ValueError('N61 brightness helper differs from the desktop manifest')
    key = 'etc/systemd/system/multi-user.target.wants/omarchy-pacman-init.service'
    link = actual.get(key, {})
    if (link.get('type'), link.get('target')) != (
            'symlink', '/usr/lib/systemd/system/omarchy-pacman-init.service'):
        raise ValueError('N61 package keyring initialization is not enabled')
    privileges = json.loads(contents['etc/omarchy/package-privileges.json'])
    for key, privilege in privileges.items():
        item = actual.get(key, {})
        for field in ('type', 'mode', 'uid', 'gid'):
            expected_value = 'directory' if field == 'type' and privilege[field] == 'dir' else privilege[field]
            if item.get(field) != expected_value:
                raise ValueError('N61 package privilege differs: ' + key)
        if privilege['type'] == 'file' and item.get('sha256') != privilege['sha256']:
            raise ValueError('N61 privileged file content differs: ' + key)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.release), indent=2))


if __name__ == '__main__':
    main()
