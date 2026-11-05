"""The orchard snapshot a build uses: its producers run as commands; none of its Python is imported.

The snapshot is a directory with orchard's src/ and data: a checkout, the
newest nightly's tooling (what the orchard launcher runs), or a release's
orchard-source.tar.gz unpacked (orchard docs/distribution-contract.md).
orchard build names it in ORCHARD_CHECKOUT; a build without orchard passes
--orchard DIR.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib


def directory(explicit=None):
    value = explicit or os.environ.get('ORCHARD_CHECKOUT')
    if not value:
        raise ValueError('Name the orchard snapshot: --orchard DIR, or ORCHARD_CHECKOUT (orchard build sets it)')
    path = Path(value).expanduser().resolve()
    if not (path / 'src/orchard').is_dir():
        raise ValueError(f'{path} is no orchard snapshot (it has no src/orchard)')
    return path


def environment(root):
    """The environment an orchard command runs in: the snapshot's Python first."""
    return {**os.environ, 'PYTHONPATH': str(Path(root) / 'src'), 'ORCHARD_CHECKOUT': str(root)}


def command(root, module, *argv, **kwargs):
    """Run orchard's producer MODULE (python -m MODULE ARGV) from the snapshot ROOT."""
    argv = [sys.executable, '-m', module, *map(str, argv)]
    print('+', ' '.join(argv), flush=True)
    return subprocess.run(argv, env=environment(root), check=True, **kwargs)


def revision(root):
    """{'commit', 'modified'} of a snapshot that is a git checkout or clone; None otherwise."""
    def git(*arguments):
        return subprocess.run(['git', '-C', str(root), *arguments], capture_output=True, text=True,
                              check=True).stdout.strip()
    try:
        return {'commit': git('rev-parse', 'HEAD'),
                'modified': bool(git('status', '--porcelain', '--untracked-files=no'))}
    except (OSError, subprocess.CalledProcessError):
        return None


def private_firmware(root):
    """Where any board the snapshot describes puts its private firmware; none of it may be public."""
    destinations = set()
    for descriptor in sorted((Path(root) / 'devices').glob('*/device.toml')):
        if descriptor.is_symlink() or descriptor.parent.is_symlink():
            continue
        described = tomllib.loads(descriptor.read_text())
        if 'firmware' not in described:  # A board with identity only has no firmware to keep private.
            continue
        recipe = described['firmware']['recipe']
        if '\\' in recipe or ':' in recipe or any(part in ('', '.', '..') for part in recipe.split('/')):
            raise ValueError(f'{descriptor}: unsafe firmware recipe {recipe}')
        destinations |= {row['destination'] for row in
                         json.loads((descriptor.parent / recipe).read_text())['outputs']}
    return destinations


def dtbs(root, boards):
    """{board: DTB name} of BOARDS, from the snapshot's device data (devices/BOARD/device.toml [kernel])."""
    result = {}
    for board in boards:
        descriptor = Path(root) / 'devices' / board / 'device.toml'
        dtb = tomllib.loads(descriptor.read_text()).get('kernel', {}).get('dtb')
        if not isinstance(dtb, str) or '/' in dtb or not dtb:
            raise ValueError(f'{descriptor}: [kernel] names no dtb')
        result[board] = dtb
    return result
