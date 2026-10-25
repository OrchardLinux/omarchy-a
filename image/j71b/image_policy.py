"""Omarchy image-owned readiness, privilege and init policy."""
import json
import os
from pathlib import Path
import subprocess

DIAGNOSTICS_EXECUTABLE = '/usr/libexec/omarchy-dropbear'


def stop_diagnostics():
    subprocess.run(['systemctl', 'stop', 'omarchy-diagnostics.service'],
                   check=True, capture_output=True, timeout=15)

from permissions import verify as verify_privileges, verify_session_access

INIT = '/usr/lib/systemd/systemd'


def ready(*, ssh_revoked=False):
    path = Path('/run/user/1000/omarchy-desktop-ready.json')
    try:
        if path.is_symlink() or path.stat().st_uid != 1000:
            return False
        record = json.loads(path.read_text())
        if record['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            return False
        pid = int(record['shell_pid'])
        process = Path('/proc') / str(pid)
        return (process.stat().st_uid == 1000 and
                (process / 'exe').readlink().name in ('qs', 'quickshell') and
                Path(record['wayland_socket']).is_socket() and
                Path(record['wayland_socket']).stat().st_uid == 1000)
    except (OSError, ValueError, KeyError):
        return False



def validate_root(root, release):
    for helper in ('usr/lib/systemd/systemd', 'usr/libexec/j71b-check-platform',
                   'usr/libexec/j71b-charge-lease', 'usr/libexec/omarchy-diagnostics'):
        if not os.access(root / helper, os.X_OK):
            raise ValueError('Missing executable: ' + helper)
    root_release = json.loads((root / 'etc/orchard/release.json').read_text())
    if root_release['release'] != release['release']:
        raise ValueError('Root/recovery release mismatch')


def validate_handoff(root):
    for helper in ('usr/lib/systemd/systemd', 'usr/libexec/j71b-check-platform',
                   'usr/libexec/j71b-charge-lease', 'usr/libexec/omarchy-diagnostics'):
        if not os.access(root / helper, os.X_OK):
            raise ValueError('Handoff executable missing: ' + helper)


def diagnostics():
    logs = {}
    for name in ('omarchy-desktop-ready.log', 'omarchy-shell.log'):
        path = Path('/run/user/1000') / name
        try:
            if not path.is_symlink() and path.stat().st_uid == 1000:
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size - 12000))
                    logs[name] = stream.read(12000).decode(errors='replace')
        except OSError:
            pass
    return logs
