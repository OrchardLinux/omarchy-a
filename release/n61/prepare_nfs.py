"""Expand an audited N61 image and bind one private NFS root session."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import uuid

from orchard_cli import firmware

from .audit import audit
from .common import ARCHITECTURE, KERNEL_RELEASE, PROFILE, encoded, name, sha


def extract(archive, root):
    with tarfile.open(archive, 'r|gz') as stream:
        for member in stream:
            key = name(member.name)
            path = root / key
            if not path.parent.resolve().is_relative_to(root.resolve()):
                raise ValueError('N61 extraction parent escapes the staging root')
            path.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                if path.is_symlink():
                    raise ValueError('N61 directory would replace a link')
                path.mkdir(exist_ok=True)
                os.chown(path, member.uid, member.gid)
                path.chmod(member.mode)
            elif member.issym():
                target = member.linkname
                if target.startswith('/'):
                    target = posixpath.relpath(target.lstrip('/'), posixpath.dirname(key) or '.')
                destination = posixpath.normpath(posixpath.join(posixpath.dirname(key), target))
                if destination == '..' or destination.startswith('../'):
                    raise ValueError('N61 extraction link escapes the staging root')
                path.symlink_to(target)
                os.lchown(path, member.uid, member.gid)
            elif member.isfile():
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'wb') as output, stream.extractfile(member) as source:
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fchown(output.fileno(), member.uid, member.gid)
                    os.fchmod(output.fileno(), member.mode)
            else:
                raise ValueError('Unsupported N61 extraction entry')


def require_case_sensitive(root):
    probe = root / '.n61-case-probe'
    probe.write_bytes(b'')
    sensitive = not (root / '.N61-CASE-PROBE').exists()
    probe.unlink()
    if not sensitive:
        raise ValueError('N61 NFS roots require a case-sensitive Linux filesystem')


def verify_privileges(root):
    entries = json.loads((root / 'etc/omarchy/package-privileges.json').read_text())
    for key, expected in entries.items():
        path = root / name(key)
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Linked N61 privileged package entry')
        info = path.stat()
        if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (expected['uid'], expected['gid'], expected['mode']):
            raise ValueError('Staged N61 package permissions differ: ' + key)
        if expected['type'] == 'file' and sha(path) != expected['sha256']:
            raise ValueError('Staged N61 privileged file differs: ' + key)


def owner_access(root, authorized_key):
    key = Path(authorized_key).read_text().strip()
    if len(key) > 16384 or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\r\n]+)?', key):
        raise ValueError('Expected one explicit owner Ed25519 public key')
    for relative, uid in (('root/.ssh', 0), ('home/tablet/.ssh', 1000)):
        directory = root / relative
        if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
            raise ValueError('Linked N61 owner SSH directory')
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chown(directory, uid, uid)
        directory.chmod(0o700)
        path = directory / 'authorized_keys'
        path.write_text(key + '\n')
        os.chown(path, uid, uid)
        path.chmod(0o600)
    host_key = root / 'etc/ssh/ssh_host_ed25519_key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(host_key)], check=True)
    host_key.chmod(0o600)
    directory = root / 'etc/ssh/sshd_config.d'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / '10-n61-owner.conf').write_text(
        'HostKey /etc/ssh/ssh_host_ed25519_key\n'
        'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPubkeyAuthentication yes\n'
        'PermitRootLogin prohibit-password\nAllowUsers root tablet\nUsePAM yes\n')
    wants = root / 'etc/systemd/system/multi-user.target.wants'
    wants.mkdir(parents=True, exist_ok=True)
    (wants / 'sshd.service').symlink_to('../../../../usr/lib/systemd/system/sshd.service')
    return sha(Path(authorized_key))


def read_firmware(mixin, receipt):
    """Validate the shared CLI's private mixin against the installed N61 recipe."""
    mixin, receipt = Path(mixin), Path(receipt)
    if mixin.is_symlink() or receipt.is_symlink() or not mixin.is_file() or not receipt.is_file():
        raise ValueError('Expected regular private firmware mixin and receipt files')
    record = json.loads(receipt.read_text())
    if not isinstance(record, dict) or (record.get('schema'), record.get('kind')) != (1, 'private-mixin'):
        raise ValueError('Expected the native private firmware mixin receipt')
    if (not 0 < mixin.stat().st_size <= 16 * 1024 * 1024 or
            mixin.stat().st_size != record.get('bytes') or sha(mixin) != record.get('sha256')):
        raise ValueError('Private firmware mixin differs from its receipt')
    expected = {output['destination']: output['sha256'] for output in firmware.recipe_for(PROFILE)['outputs']}
    if any(name(key) != key or not key.startswith('lib/firmware/') for key in expected):
        raise ValueError('N61 firmware recipe has unsafe destinations')
    records, expanded = {}, 0
    with tarfile.open(mixin, 'r|gz') as stream:
        for member in stream:
            key = name(member.name)
            if (key != member.name or key in records or not member.isfile() or
                    key not in expected.keys() | {'mixin.json'} or len(records) >= len(expected) + 1):
                raise ValueError('Private firmware mixin contains unexpected paths, links or duplicates')
            expanded += member.size
            if expanded > 32 * 1024 * 1024 or (key == 'mixin.json' and member.size > 65536):
                raise ValueError('Private firmware mixin exceeds its expanded limit')
            records[key] = stream.extractfile(member).read()
    metadata = json.loads(records.pop('mixin.json', b'{}'))
    if not isinstance(metadata, dict) or (metadata.get('schema'), metadata.get('profile')) != (1, PROFILE):
        raise ValueError('Private firmware mixin is not for N61')
    if (not isinstance(metadata.get('files'), dict) or set(records) != set(expected) or
            set(metadata['files']) != set(expected)):
        raise ValueError('Private firmware mixin must contain exactly the N61 recipe outputs')
    for key, data in records.items():
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected[key] or metadata['files'][key] != {'bytes': len(data), 'sha256': digest}:
            raise ValueError('Private firmware differs from the N61 recipe: ' + key)
    return records, {**record, 'files': metadata['files']}


def stage_firmware(root, records):
    for key, data in records.items():
        # Arch's /lib points at /usr/lib. Write through real directories only.
        parts = ('usr/' + key).split('/')
        current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                created = False
                try:
                    os.mkdir(part, 0o755, dir_fd=current)
                    created = True
                except FileExistsError:
                    pass
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                os.close(current)
                current = following
                if created:
                    os.fchown(current, 0, 0)
                    os.fchmod(current, 0o755)
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=current)
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
                output.flush()
                os.fchown(output.fileno(), 0, 0)
                os.fchmod(output.fileno(), 0o600)
        finally:
            os.close(current)


def prepare(release, destination, authorized_key=None, *, firmware_mixin=None, firmware_receipt=None):
    release, destination = Path(release), Path(destination).expanduser().absolute()
    receipt = audit(release)
    record_path = destination.parent / (destination.name + '.private.json')
    if (destination == Path('/') or destination.exists() or destination.is_symlink() or
            record_path.exists() or record_path.is_symlink()):
        raise ValueError('Choose a new private N61 NFS root and staging receipt')
    if os.geteuid() != 0:
        raise ValueError('N61 NFS staging requires root to retain guest UID/GID and package modes')
    if (firmware_mixin is None) != (firmware_receipt is None):
        raise ValueError('Private N61 firmware requires both --firmware-mixin and --firmware-receipt')
    private_files, private_receipt = read_firmware(firmware_mixin, firmware_receipt) if firmware_mixin else ({}, None)
    destination.mkdir(parents=True, mode=0o755)
    try:
        os.chown(destination, 0, 0)
        destination.chmod(0o755)
        require_case_sensitive(destination)
        extract(release / 'rootfs.tar.gz', destination)
        verify_privileges(destination)
        stage_firmware(destination, private_files)
        for directory in ('dev', 'proc', 'sys', 'run'):
            path = destination / directory
            if path.is_symlink() or not path.is_dir():
                raise ValueError('N61 handoff needs a real ' + directory + ' directory')
        identity = {'schema': 1, 'kind': 'orchard.nfs-root', 'profile': PROFILE,
                    'architecture': ARCHITECTURE, 'kernel_release': KERNEL_RELEASE,
                    'root_id': str(uuid.uuid4()), 'image_sha256': receipt['root']['sha256'],
                    'image_receipt_sha256': sha(release / 'rootfs.json')}
        path = destination / 'etc/orchard/nfs-root.json'
        path.write_bytes(encoded(identity))
        path.chmod(0o644)
        owner_hash = owner_access(destination, authorized_key) if authorized_key else None
        for key, value in (('hostname', 'omarchy-n61\n'),
                           ('hosts', '127.0.0.1 localhost\n::1 localhost\n127.0.1.1 omarchy-n61\n')):
            path = destination / 'etc' / key
            path.write_text(value)
            path.chmod(0o644)
        path = destination / 'etc/orchard/nfs-root.json'
        result = {'schema': 1, 'private': True, 'publishable': False, 'profile': PROFILE,
                  'release': receipt['release'], 'root_identity': identity,
                  'root_identity_sha256': sha(path), 'owner_authorized_key_sha256': owner_hash,
                  'firmware_mixin': private_receipt,
                  'root_identity_file': str(path),
                  'link_policy': 'Guest absolute links normalized to equivalent relative staging links'}
        record_path.write_bytes(encoded(result))
        record_path.chmod(0o600)
    except BaseException:
        shutil.rmtree(destination)
        raise
    print('Prepared N61 NFS root:', destination)
    print('RAM handoff receipt:', path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--authorized-key', type=Path)
    parser.add_argument('--firmware-mixin', type=Path, help='native private N61 firmware mixin.tar.gz')
    parser.add_argument('--firmware-receipt', type=Path, help='matching native mixin.json receipt')
    args = parser.parse_args()
    prepare(args.release, args.destination, args.authorized_key,
            firmware_mixin=args.firmware_mixin, firmware_receipt=args.firmware_receipt)


if __name__ == '__main__':
    main()
