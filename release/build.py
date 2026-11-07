#!/usr/bin/env python3
"""Produce one release for every platform of one architecture: the root as a block image, its logo, and a manifest naming orchard's files.

The root image holds no kernel. orchard's platform layer (kernel, DTBs,
modules) goes next to it, and the installer boots that kernel and writes the
layer into the root (orchard docs/boot-contract.md). A release has one root:
aarch64 for orchard's arm64 platforms (platforms.toml), armv7h for its 32-bit
ones (a release of its own, from orchard's 32-bit index).
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tomllib

from .public_root import build as build_root, sha
from release import snapshot
from release.architecture import platform_arch, validate
from release.manifests import INDEXES, ORCHARD_ARCHITECTURES, write as write_manifests


def orchard_files(args):
    """Kernels, loaders and install tools into the release, listed in orchard's index of the root's architecture.

    Finished from a published orchard build (--orchard-release), or from this build's inputs:
    a developer's own kernel. Only the former is linked instead of hosted when published.
    """
    if args.orchard_release:
        # --architecture only for 32-bit: the arm64 index is the default (and older orchards lack the option).
        source = ('--release', args.orchard_release,
                  *(('--architecture', ORCHARD_ARCHITECTURES[args.architecture]) if args.architecture != 'aarch64' else ()),
                  *(part for name in args.platform for part in ('--platform', name)))
    else:
        source = ('--inputs', args.inputs)
    snapshot.command(args.orchard, 'orchard.image.platforms_index', args.output, *source, stdout=subprocess.DEVNULL)
    return tomllib.loads((args.output / INDEXES[args.architecture]).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for name in ('base', 'base-receipt', 'splash', 'logo', 'busybox', 'dropbear', 'dropbearkey',
                 'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--architecture', choices=sorted(INDEXES), default='aarch64', help="the root's architecture")
    parser.add_argument('--platform', action='append', default=[],
                        help='with --orchard-release: only this platform; repeat (default: every one of the '
                             "architecture; armv7h names its platforms)")
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--orchard-release', metavar='TAG', help="take orchard's files finished from this build")
    source.add_argument('--inputs', type=Path, help="orchard's inputs for this build (python -m orchard.inputs)")
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new release output directory')
    # Reject missing distro inputs before anything is assembled.
    for name in ('base', 'base_receipt', 'splash', 'logo', 'busybox', 'dropbear', 'dropbearkey'):
        if not getattr(args, name).is_file():
            parser.error(f'Missing input file: {getattr(args, name)}')
    for name in ('cursor_tools', 'bluetooth_tools', 'labwc_tools'):
        if not getattr(args, name).is_dir():
            parser.error(f'Missing tools directory: {getattr(args, name)}')
    try:
        validate(args.architecture)
        args.orchard = snapshot.directory(args.orchard)
        document = json.loads(args.inputs.read_text()) if args.inputs else None
        # Every platform of the release runs the root's architecture.
        for name in (*args.platform, *((document or {}).get('platforms') or ())):
            if platform_arch(name, args.orchard) != args.architecture:
                raise ValueError(f'{name} is not a platform of the {args.architecture} root')
        if args.orchard_release and args.architecture != 'aarch64' and not args.platform:
            raise ValueError('Name the platforms of the armv7h release with --platform')
    except (ValueError, OSError) as error:
        parser.error(str(error))
    revision = (document or {}).get('orchard') or snapshot.revision(args.orchard)
    if not revision:
        parser.error(f'{args.orchard} is no git checkout and no --inputs names its revision')
    public_root = build_root(args.base, args.base_receipt, args.output, args.release,
                             args.cursor_tools, args.bluetooth_tools, args.labwc_tools,
                             tools={'dropbear': args.dropbear, 'dropbearkey': args.dropbearkey, 'busybox': args.busybox},
                             splash=args.splash, architecture=args.architecture)
    offered = orchard_files(args)
    snapshot.command(args.orchard, 'orchard.image.root_image', args.output / 'rootfs.tar.zst', '--output', args.output)
    root = json.loads((args.output / 'root-image.json').read_text())
    if args.architecture == 'aarch64':   # a 32-bit release has no logo
        shutil.copyfile(args.logo, args.output / 'logo.bin')
    published = write_manifests(args.output, args.release, root, offered, revision, architecture=args.architecture)
    # Assembly provenance is separate from the public installation contract.
    receipt = {'schema': 2, 'release': args.release, 'architecture': args.architecture, 'orchard': revision,
               'public_root': public_root, 'platforms': offered['platforms'],
               'inputs': {name: {'bytes': path.stat().st_size, 'sha256': sha(path)}
                          for name, path in vars(args).items() if isinstance(path, Path) and path.is_file()}}
    (args.output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Public release ready:', published)
    print('Pinned index:', args.output / 'index.toml')


if __name__ == '__main__':
    main()
