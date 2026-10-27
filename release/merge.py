#!/usr/bin/env python3
"""Combine separately built per-device releases into one directory and index."""
import argparse
from pathlib import Path
import shutil

from orchard_hardware.image.integrity import sha
from release.manifests import METHOD, write_index


def merge(primary, others):
    """Copy every file except the index; refuse differing names. Pongo is shared."""
    copies = {}
    for directory in others:
        if directory.is_symlink() or not directory.is_dir() or directory.resolve() == primary.resolve():
            raise ValueError('Expected a separate release directory: ' + str(directory))
        for source in sorted(directory.iterdir()):
            if source.name == 'index.toml':
                continue
            if source.is_symlink() or not source.is_file():
                raise ValueError('Release directories contain only regular files: ' + source.name)
            target = primary / source.name
            existing = copies.get(target, target if target.exists() or target.is_symlink() else None)
            if existing is not None:
                if existing.is_symlink() or sha(existing) != sha(source):
                    raise ValueError('Conflicting release file: ' + source.name)
                continue
            copies[target] = source
    # Every conflict is refused before the first copy.
    for target, source in copies.items():
        shutil.copyfile(source, target)
    return write_index(primary, sorted(primary.glob('*-' + METHOD + '.toml')), replace=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-dir', required=True, type=Path, help='existing release receiving the others')
    parser.add_argument('--add', required=True, type=Path, action='append', help='another device release directory')
    args = parser.parse_args()
    print(merge(args.release_dir, args.add))


if __name__ == '__main__':
    main()
