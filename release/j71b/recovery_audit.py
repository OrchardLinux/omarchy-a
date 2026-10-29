"""Read-only checks inside the actual framed initramfs, without extracting it."""
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat

from orchard_hardware import firmware_path


def read_newc(stream):
    total = 0
    seen = set()
    while True:
        header = stream.read(110)
        if len(header) != 110 or header[:6] != b'070701':
            raise ValueError('Invalid/truncated recovery newc header')
        fields = [int(header[i:i+8], 16) for i in range(6, 110, 8)]
        mode, size, name_size = fields[1], fields[6], fields[11]
        if not 0 < name_size <= 4096 or size > 256 * 1024**2 or len(seen) > 100000:
            raise ValueError('Recovery member exceeds limits')
        label = stream.read(name_size)
        if len(label) != name_size or label[-1:] != b'\0' or b'\0' in label[:-1]:
            raise ValueError('Invalid recovery member name')
        name = label[:-1].decode()
        stream.read(-(110 + name_size) % 4)
        if name == 'TRAILER!!!':
            if size or stream.read(513) != b'\0' * 512:
                raise ValueError('Unexpected recovery trailer data')
            return
        path = PurePosixPath(name)
        if str(path) == '.' or path.is_absolute() or '..' in path.parts or name in seen or fields[2:4] != [0, 0]:
            raise ValueError('Unsafe/duplicate/non-root recovery member')
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
            raise ValueError('Special recovery member')
        seen.add(name)
        data = stream.read(size)
        if len(data) != size:
            raise ValueError('Truncated recovery member')
        stream.read(-size % 4)
        total += size
        if total > 1024**3:
            raise ValueError('Recovery expansion exceeds limit')
        yield name, mode, data


def audit_runtime(image, root_spec, release):
    receipt = json.loads(Path(str(image) + '.json').read_text())
    part = next(row for row in receipt['components'] if row['name'] == 'initramfs')
    hashes, modes, records = {}, {}, {}
    firmware = json.loads(firmware_path('j71b').read_text())
    private = {row['destination'] for row in firmware['outputs']}
    names = set()
    with image.open('rb') as raw:
        raw.seek(part['offset'])
        with gzip.GzipFile(fileobj=raw) as stream:
            for name, mode, data in read_newc(stream):
                names.add(name)
                modes[name] = mode
                if name.removeprefix('usr/') in private:
                    raise ValueError('Private firmware found in recovery')
                if stat.S_ISREG(mode):
                    if name.startswith(('run/orchard/', 'run/recovery/', 'root/.ssh/')):
                        raise ValueError('Private session state found in public recovery')
                    hashes[name] = hashlib.sha256(data).hexdigest()
                    if name in ('etc/orchard/release.json', 'etc/orchard/public.SHA256SUMS'):
                        records[name] = data
    prefix = 'usr/libexec/orchard-j71b/'
    required = {prefix + name for name in ('device.py', 'archive.py', 'staging.py', 'handoff.py',
                                          'storage.py', 'identity.py', 'adt.py')}
    required |= {'init', 'usr/bin/orchard-device', 'sbin/capture-adt', 'sbin/authorize-key',
                 'sbin/recovery-start-ssh', 'usr/bin/python3', 'etc/orchard/firmware.json',
                 'usr/sbin/blkid', 'usr/sbin/sfdisk', 'usr/sbin/mke2fs', 'etc/mke2fs.conf'}
    if not required <= names:
        raise ValueError('Missing recovery endpoint/policy/runtime')
    for name in ('init', 'usr/bin/orchard-device', 'sbin/capture-adt', 'sbin/authorize-key', 'sbin/recovery-start-ssh',
                 'usr/sbin/blkid', 'usr/sbin/sfdisk', 'usr/sbin/mke2fs'):
        if not stat.S_ISREG(modes[name]) or modes[name] & 0o111 != 0o111:
            raise ValueError('Recovery helper is not executable: ' + name)
    if any('omarchy-j71b' in name or name == 'usr/bin/omarchy-device' for name in names):
        raise ValueError('Old agent namespace remains in recovery')
    config = json.loads(records['etc/orchard/release.json'])
    expected = {key: root_spec[key] for key in ('sha256', 'bytes', 'expanded_bytes', 'members', 'compression')}
    if config['root'] != expected or config['release'] != release or config['protocol'] != 1 or config['profile'] != 'j71b':
        raise ValueError('Recovery is not locked to the published root')
    public = records['etc/orchard/public.SHA256SUMS'].decode()
    for line in public.splitlines():
        digest, name = line.split('  ', 1)
        if hashes.get(name.lstrip('/')) != digest:
            raise ValueError('Recovery public runtime differs: ' + name)
    return {'members': len(names), 'hashes': hashes, 'public': public}
