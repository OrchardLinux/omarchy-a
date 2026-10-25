"""Package-defined privileged metadata from the base's pacman MTREE records.

Ownership changes can clear setuid/setgid bits. Restore only package-authenticated
privileged entries, checking file content before granting those bits.
"""
import gzip
import hashlib
from pathlib import PurePosixPath
import re
import tarfile


def parse_mtree(text):
    defaults = {}
    for line in text.replace('\\\n', '').splitlines():
        fields = line.split()
        if not fields or fields[0].startswith('#'):
            continue
        if fields[0] == '/unset':
            for key in fields[1:]:
                if key == 'all':
                    defaults.clear()
                else:
                    defaults.pop(key, None)
            continue
        attributes = dict(field.split('=', 1) for field in fields[1:] if '=' in field)
        if fields[0] == '/set':
            defaults.update(attributes)
            continue
        attributes = {**defaults, **attributes}
        mode = int(attributes.get('mode', '0'), 8)
        if not mode & 0o6000:
            continue
        name = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), fields[0])
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\0' in name or str(path) == '.':
            raise ValueError('Unsafe package permission path')
        kind = attributes.get('type')
        if kind not in ('file', 'dir'):
            raise ValueError('Special permissions on unsupported package entry')
        record = {'uid': int(attributes['uid']), 'gid': int(attributes['gid']),
                  'mode': mode, 'type': kind}
        if kind == 'file':
            digest = attributes.get('sha256digest', '')
            if not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('Privileged package file lacks a content digest')
            record.update(sha256=digest, bytes=int(attributes['size']))
        yield str(path), record


def privileged_entries(base):
    result = {}
    with tarfile.open(base, 'r|gz') as archive:
        for member in archive:
            name = member.name.removeprefix('./')
            if not (name.startswith('var/lib/pacman/local/') and name.endswith('/mtree') and member.isfile()):
                continue
            if member.size > 16 * 1024 * 1024:
                raise ValueError('Package metadata exceeds limit')
            data = archive.extractfile(member).read()
            if data.startswith(b'\x1f\x8b'):
                data = gzip.decompress(data)
            for path, record in parse_mtree(data.decode()):
                if path in result and result[path] != record:
                    raise ValueError('Conflicting package permission metadata: ' + path)
                result[path] = record
    sudo = result.get('usr/bin/sudo', {})
    if sudo.get('uid') != 0 or sudo.get('mode') != 0o4755:
        raise ValueError('Missing package-defined sudo privilege contract')
    return result


def apply(member, data, expected, seen_digests):
    if expected['type'] == 'dir':
        if not member.isdir():
            raise ValueError('Privileged package directory changed type: ' + member.name)
    else:
        if member.isfile():
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != expected['bytes']:
                raise ValueError('Privileged package file changed size: ' + member.name)
        elif member.islnk():
            digest = seen_digests.get(member.linkname.removeprefix('./'))
        else:
            raise ValueError('Privileged package file changed type: ' + member.name)
        if digest != expected['sha256']:
            raise ValueError('Privileged package content differs: ' + member.name)
        seen_digests[member.name] = digest
    member.uid, member.gid, member.mode = expected['uid'], expected['gid'], expected['mode']
