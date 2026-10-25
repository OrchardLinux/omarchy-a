"""Verify package-defined privileged files before a staged root can activate."""
import hashlib
import json
import os
from pathlib import Path
import stat

from archive import parent_fd, safe_name


def verify_session_access(root):
    """The tablet must traverse/read/execute the public readiness entrypoint.

    Do not check the private staging root itself: it becomes 0755 only when
    promoted. Open every descendant without following links or creating paths.
    """
    current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parts = ('usr', 'libexec', 'omarchy-desktop-ready')
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            following = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = following
            info = os.fstat(current)
            if (info.st_mode & 0o005 != 0o005 or
                    (index == len(parts) - 1 and not stat.S_ISREG(info.st_mode))):
                raise ValueError('Tablet cannot access desktop readiness entrypoint: ' + part)
    finally:
        os.close(current)


def verify(root, ownership=True):
    records = json.loads((Path(root) / 'etc/omarchy/package-privileges.json').read_text())
    sudo = records.get('usr/bin/sudo', {})
    if sudo.get('uid') != 0 or sudo.get('mode') != 0o4755:
        raise ValueError('Missing sudo ownership/setuid contract')
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name, expected in records.items():
            safe_name(name)
            parent, leaf = parent_fd(root_fd, name)
            try:
                fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    valid_type = stat.S_ISREG(info.st_mode) if expected['type'] == 'file' else stat.S_ISDIR(info.st_mode)
                    if (not valid_type or stat.S_IMODE(info.st_mode) != expected['mode'] or
                            (ownership and (info.st_uid, info.st_gid) != (expected['uid'], expected['gid']))):
                        raise ValueError('Privileged package ownership/mode differs: ' + name)
                    if expected['type'] == 'file':
                        digest = hashlib.sha256()
                        for block in iter(lambda: os.read(fd, 1048576), b''):
                            digest.update(block)
                        if digest.hexdigest() != expected['sha256']:
                            raise ValueError('Privileged package content differs: ' + name)
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
    finally:
        os.close(root_fd)
    return len(records)
