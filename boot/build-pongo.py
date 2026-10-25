#!/usr/bin/env python3
"""Build distro-branded Pongo from pinned sources on macOS."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new output path')
    pin = dict(line.split('=', 1) for line in (HERE / 'pongo/upstream.lock').read_text().splitlines() if '=' in line)
    source = HERE / 'pongo/.work/source'
    patch = HERE / 'pongo/patches/0001-omarchy-splash.patch'
    def run(*command):
        subprocess.run(command, check=True)
    if args.resume:
        if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != pin['commit']:
            raise ValueError('Wrong Pongo revision')
        run('git', '-C', str(source), 'apply', '--reverse', '--check', str(patch))
    else:
        if source.exists():
            parser.error('Source exists; use --resume after checking its identity')
        source.mkdir(parents=True)
        run('git', '-C', str(source), 'init', '-q')
        run('git', '-C', str(source), 'remote', 'add', 'origin', pin['url'])
        run('git', '-C', str(source), 'fetch', '--depth', '1', 'origin', pin['commit'])
        run('git', '-C', str(source), 'checkout', '-q', '--detach', 'FETCH_HEAD')
        run('git', '-C', str(source), 'apply', '--check', str(patch))
        run('git', '-C', str(source), 'apply', str(patch))
    run('git', '-C', str(source), 'submodule', 'update', '--init', '--recursive', '--depth', '1')
    if subprocess.check_output(['git', '-C', str(source / 'newlib'), 'rev-parse', 'HEAD'], text=True).strip() != pin['newlib_commit']:
        raise ValueError('Wrong pinned newlib revision')
    run(sys.executable, str(HERE / 'pongo/generate-logo.py'), '--output',
        str(source / 'src/drivers/framebuffer/omarchy-logo.h'))
    run('make', '-C', str(source), '-j4', 'PONGO_CFLAGS=-DOMARCHY_SPLASH', 'build/Pongo.bin')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as target, (source / 'build/Pongo.bin').open('rb') as binary:
        shutil.copyfileobj(binary, target)


if __name__ == '__main__':
    main()
