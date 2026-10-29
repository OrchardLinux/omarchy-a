"""Omarchy A's N61 desktop and NFS image contract."""
import json
import os
from pathlib import Path

PROFILE = 'n61'
ARCHITECTURE = 'aarch64'
KERNEL_RELEASE = '7.3.0-rc1-orchard-apple-4k'
INIT = '/usr/lib/systemd/systemd'
PANEL = (750, 1334)
SCALE = 1.5


def ready():
    path = Path('/run/user/1000/omarchy-desktop-ready.json')
    try:
        if path.is_symlink() or path.stat().st_uid != 1000:
            return False
        record = json.loads(path.read_text())
        if record['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            return False
        process = Path('/proc') / str(int(record['shell_pid']))
        socket = Path(record['wayland_socket'])
        return (process.stat().st_uid == 1000 and
                (process / 'exe').readlink().name in ('qs', 'quickshell') and
                socket.is_socket() and socket.stat().st_uid == 1000)
    except (OSError, ValueError, KeyError):
        return False


def validate_root(root):
    for helper in ('usr/lib/systemd/systemd', 'usr/libexec/omarchy-desktop-ready'):
        if not os.access(root / helper, os.X_OK):
            raise ValueError('N61 root lacks executable ' + helper)
