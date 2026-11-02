"""Keyed build products of this checkout: out/components/NAME/KEY/ARTIFACT, rebuilt only when their inputs change.

The key is the same as orchard's distro.component gave (the inputs' modes and
contents, and extra strings), so results built before keep being reused.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

NAME = re.compile(r'[a-z0-9][a-z0-9._-]*')
IGNORE = ('.work', '.git', '__pycache__')


def _digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def entries(root, paths):
    """{relative path: "mode:sha256"} of the files under PATHS, in hashing order."""
    result = {}
    for relative in paths:
        top = root / relative
        files = [top] if top.is_file() else []
        if top.is_dir():
            for directory, dirs, names in os.walk(top):
                dirs[:] = sorted(d for d in dirs if d not in IGNORE)
                files.extend(Path(directory) / name for name in sorted(names))
        for path in files:
            result[str(path.relative_to(root))] = f'{path.stat().st_mode & 0o777}:{_digest(path)}'
    return result


def component(root, name, inputs, produce, *, artifact, extra=(), keep=2):
    """ROOT/out/components/NAME/KEY/ARTIFACT for INPUTS (paths under ROOT) and EXTRA strings.

    The same inputs reuse the earlier result; otherwise PRODUCE(path, work)
    makes ARTIFACT at path, which does not exist yet; work is kept between
    attempts of this key (out/components/.work/NAME-KEY). KEEP results per
    name stay. Returns (path, key).
    """
    root = Path(root).resolve()
    if not NAME.fullmatch(name) or '/' in artifact or artifact in ('', '.', '..'):
        raise ValueError('Invalid component name or artifact')
    found = entries(root, inputs)
    if not found:
        raise ValueError(f'{name}: no input files under {", ".join(inputs)}')
    key = hashlib.sha256(json.dumps({'inputs': found, 'extra': list(extra)}, sort_keys=True).encode()).hexdigest()
    directory = root / 'out/components' / name
    target = directory / key[:16]
    if (target / artifact).exists():
        print(f'Reusing {name}: {target.relative_to(root)}', flush=True)
        os.utime(target)  # most recently used: kept first
        return target / artifact, key
    print(f'Building {name}: {target.relative_to(root)}', flush=True)
    partial = directory / f'.partial-{key[:16]}'
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir(parents=True)
    work = root / 'out/components/.work' / f'{name}-{key[:16]}'
    work.mkdir(parents=True, exist_ok=True)
    produce(partial / artifact, work)
    if not (partial / artifact).exists():
        raise ValueError(f'{name}: the build made no {artifact}')
    if target.exists():
        shutil.rmtree(target)
    os.replace(partial, target)
    older = sorted((path for path in directory.iterdir() if path.is_dir() and path != target
                    and not path.name.startswith('.')), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in older[max(keep - 1, 0):]:
        shutil.rmtree(path)
    shutil.rmtree(work, ignore_errors=True)
    return target / artifact, key
