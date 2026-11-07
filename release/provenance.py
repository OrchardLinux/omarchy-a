"""Measure the source and finished components consumed by release assembly."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

from . import snapshot
from .public_root import sha


def file_receipt(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Provenance requires a regular file: ' + str(path))
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def component_receipt(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Provenance requires a component directory')
    manifest = file_receipt(directory / 'manifest.json')
    record = json.loads((directory / 'manifest.json').read_text())
    if record.get('schema') != 1 or not isinstance(record.get('files'), dict):
        raise ValueError('Invalid component manifest')
    files = {}
    for name, expected in sorted(record['files'].items()):
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts:
            raise ValueError('Unsafe component member')
        path = directory.joinpath(*relative.parts)
        if directory.resolve() not in path.resolve().parents or any(
                directory.joinpath(*relative.parts[:index]).is_symlink()
                for index in range(1, len(relative.parts) + 1)):
            raise ValueError('Linked or escaping component member')
        measured = file_receipt(path)
        if measured['sha256'] != expected:
            raise ValueError('Component member differs from manifest: ' + name)
        files[name] = measured
    return {'manifest': manifest, 'files': files,
            **{key: record[key] for key in ('architecture', 'source', 'compiler_image') if key in record}}


def source_identity(project):
    project = Path(project).resolve()
    try:
        top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, check=True)
        checkout = Path(top.stdout.strip()).resolve() == project
    except (OSError, subprocess.CalledProcessError):
        checkout = False
    revision = snapshot.revision(project) if checkout else None
    try:
        if not checkout:
            raise FileNotFoundError('Unversioned source snapshot')
        result = subprocess.run(['git', '-C', str(project), 'ls-files', '-z', '--cached', '--others',
                                 '--exclude-standard'], capture_output=True, check=True,
                                env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
        names = {name.decode() for name in result.stdout.split(b'\0') if name}
        if revision is not None:
            revision['modified'] = bool(subprocess.run(
                ['git', '-C', str(project), 'status', '--porcelain'], capture_output=True, check=True,
                env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}).stdout)
    except (OSError, subprocess.CalledProcessError):
        names = set()
        for directory, dirs, files in os.walk(project):
            dirs[:] = sorted(name for name in dirs if name not in ('.git', '.venv', 'out', '.work', '__pycache__'))
            names.update((Path(directory) / name).relative_to(project).as_posix() for name in files)
    entries = {}
    for name in sorted(names):
        path = project / name
        if path.is_symlink():
            entries[name] = {'mode': stat.S_IMODE(path.lstat().st_mode), 'link': os.readlink(path)}
        elif path.is_file():
            entries[name] = {'mode': stat.S_IMODE(path.stat().st_mode), **file_receipt(path)}
        else:
            entries[name] = {'missing': True}
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    return {'commit': (revision or {}).get('commit'), 'modified': (revision or {}).get('modified'),
            'tree_sha256': digest, 'files': len(entries)}


def orchard_identity(root):
    identity = source_identity(root)
    if identity['commit'] is None:
        if identity['modified'] is not None or (Path(root) / '.git').exists():
            raise ValueError('Orchard Git snapshot revision is unavailable')
    elif identity['modified'] is not False:
        raise ValueError('Choose a clean Orchard snapshot for release production')
    return identity


def input_revision(identity, declared=None):
    expected = {key: identity[key] for key in ('commit', 'modified')}
    if declared is None:
        if expected['commit'] is None:
            raise ValueError('Unversioned Orchard snapshots require matching null/null input revision metadata')
    elif (not isinstance(declared, dict) or
          any(key not in declared or declared[key] != value for key, value in expected.items())):
        raise ValueError('Orchard inputs revision differs from the producer snapshot')
    return expected


def producer_identity(orchard, project):
    return {'orchard': orchard_identity(orchard),
            'buildenv': file_receipt(Path(orchard) / 'src/orchard/buildenv.py'),
            'wrapper': file_receipt(Path(project) / 'desktop/snapshot_buildenv.py')}
