"""Shared root assembly invariants; no device, ADT or firmware access."""
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SYSTEM = PROJECT / 'system/overlay'
NETWORK_RULE = SYSTEM / 'etc/polkit-1/rules.d/60-omarchy-tablet-network.rules'
GROUPS = ('seat', 'video', 'input')


def group_membership(data: bytes, *, shadow: bool) -> bytes:
    lines = data.decode().splitlines(keepends=True)
    for group in GROUPS:
        matches = [i for i, line in enumerate(lines) if line.startswith(group + ':')]
        if len(matches) != 1:
            raise ValueError('Missing or duplicate root group: ' + group)
        i = matches[0]
        fields = lines[i].rstrip('\n').split(':')
        if len(fields) != 4 or (shadow and fields[1] != '!*') or (
                not shadow and (fields[1] != 'x' or not fields[2].isdigit())):
            raise ValueError('Unexpected group definition: ' + group)
        members = [value for value in fields[3].split(',') if value]
        if 'tablet' not in members:
            members.append('tablet')
        fields[3] = ','.join(members)
        lines[i] = ':'.join(fields) + '\n'
    return ''.join(lines).encode()
