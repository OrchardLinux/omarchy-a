"""N61 userspace archive invariants, independent of device startup."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath

from image.n61.image_policy import ARCHITECTURE, KERNEL_RELEASE, PROFILE

PROJECT = Path(__file__).resolve().parents[2]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def encoded(record):
    return (json.dumps(record, sort_keys=True, indent=2) + '\n').encode()


def name(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe N61 archive path: ' + value)
    return str(path)


def member_record(member, data=None):
    if member.isdir():
        kind = 'directory'
    elif member.isfile():
        kind = 'file'
    elif member.issym():
        kind = 'symlink'
        target = member.linkname.lstrip('/') if member.linkname.startswith('/') else posixpath.join(posixpath.dirname(member.name), member.linkname)
        if posixpath.normpath(target) == '..' or posixpath.normpath(target).startswith('../'):
            raise ValueError('N61 archive link escapes the guest root')
    else:
        raise ValueError('Unsupported N61 archive entry: ' + member.name)
    record = {'type': kind, 'mode': member.mode, 'uid': member.uid, 'gid': member.gid}
    if kind == 'file':
        record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    if kind == 'symlink':
        record['target'] = member.linkname
    return record


def aarch64(data):
    return len(data) >= 64 and data[:6] == b'\x7fELF\x02\x01' and data[18:20] == b'\xb7\x00'
