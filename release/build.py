#!/usr/bin/env python3
"""Produce one release for every platform: the root, per platform a recovery and orchard's layer, Pongo, manifest.

The root image holds no kernel. orchard's platform layer (kernel, DTBs,
modules) goes next to it, and the installer writes it into the root
(orchard docs/boot-contract.md). The recovery of a platform boots every board
of it, from the same kernel bundle as its layer.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from .public_root import build as build_root, sha
from release import snapshot
from release.manifests import write as write_manifests


def kernels(args, document=None):
    """{platform: staged kernel bundle}: explicit --kernel-dir, else orchard's inputs (orchard.inputs).

    Without --platform a release covers every platform the inputs name, or
    every one given as --kernel-dir.
    """
    offered = dict((document or {}).get('platforms', {}))
    explicit = {}
    for value in args.kernel_dir or ():
        name, separator, path = value.partition('=')
        if not separator or not name or (offered and name not in offered):
            raise ValueError(f'Use --kernel-dir PLATFORM=DIRECTORY with a platform of: '
                             f'{", ".join(sorted(offered)) or "the inputs (--inputs)"}')
        explicit[name] = Path(path)
    known = sorted(set(offered) | set(explicit))
    selected = args.platform or known
    unknown = sorted(set(selected) - set(known))
    if unknown or not selected:
        raise ValueError(f'Unknown platform {", ".join(unknown) or "(none)"}; known: {", ".join(known) or "none"}')
    return {name: explicit.get(name) or Path(offered[name]['kernel']) for name in selected}


def layer(args, name, bundle):
    """orchard's platform layer of NAME (orchard.image.platform), and its receipt."""
    receipt = args.output / '.work' / f'platform-{name}.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    snapshot.command(args.orchard, 'orchard.image.platform', name, '--output', args.output, '--kernel-dir', bundle,
                     '--busybox', args.busybox, '--receipt', receipt, stdout=subprocess.DEVNULL)
    return json.loads(receipt.read_text())


def recovery(args, name, bundle, boards, root_receipt):
    """The platform's RAM recovery, which starts every board of it; m1n1 picks the DTB."""
    dtbs = [bundle / 'dtbs' / (dtb + '.dtb') for dtb in sorted(set(boards.values()))]
    missing = [path.name for path in dtbs if not path.is_file()]
    if missing:
        raise ValueError(f'The {name} kernel bundle lacks device DTBs: ' + ', '.join(missing))
    output = args.output / f'recovery-{name}.bin'
    command = [*(f'--dtb={path}' for path in dtbs)]
    for option in ('base', 'base_receipt', 'loader', 'logo', 'busybox', 'dropbear', 'dropbearkey',
                   'wpa_supplicant', 'wpa_cli', 'iw'):
        command.extend(['--' + option.replace('_', '-'), str(getattr(args, option))])
    command.extend(['--kernel', str(bundle / 'Image.gz'), '--modules-dir', str(bundle / 'lib/modules'),
                    '--root-receipt', str(root_receipt), '--output', str(output)])
    snapshot.command(args.orchard, 'orchard.image.recovery', *command)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for name in ('base', 'base-receipt', 'loader', 'splash', 'logo', 'pongo', 'busybox', 'dropbear', 'dropbearkey',
                 'wpa-supplicant', 'wpa-cli', 'iw', 'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    parser.add_argument('--inputs', type=Path, help="orchard's inputs for this build (python -m orchard.inputs)")
    parser.add_argument('--kernel-dir', action='append', metavar='PLATFORM=DIRECTORY',
                        help="a platform's staged kernel bundle; repeat; others come from --inputs")
    parser.add_argument('--platform', action='append',
                        help='only this platform (repeat); for development, a release covers every platform')
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new release output directory')
    # Reject missing distro inputs before anything is assembled.
    for name in ('base', 'base_receipt', 'loader', 'splash', 'logo', 'pongo', 'busybox', 'dropbear', 'dropbearkey',
                 'wpa_supplicant', 'wpa_cli', 'iw'):
        if not getattr(args, name).is_file():
            parser.error(f'Missing input file: {getattr(args, name)}')
    for name in ('cursor_tools', 'bluetooth_tools', 'labwc_tools'):
        if not getattr(args, name).is_dir():
            parser.error(f'Missing tools directory: {getattr(args, name)}')
    try:
        args.orchard = snapshot.directory(args.orchard)
        document = json.loads(args.inputs.read_text()) if args.inputs else None
        bundles = kernels(args, document)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    revision = (document or {}).get('orchard') or snapshot.revision(args.orchard)
    if not revision:
        parser.error(f'{args.orchard} is no git checkout and no --inputs names its revision')
    root = build_root(args.base, args.base_receipt, args.output, args.release,
                      args.cursor_tools, args.bluetooth_tools, args.labwc_tools,
                      tools={'dropbear': args.dropbear, 'dropbearkey': args.dropbearkey, 'busybox': args.busybox},
                      splash=args.splash)
    platforms = {}
    for name, bundle in bundles.items():
        files = layer(args, name, bundle)
        boards = files.pop('boards')
        image = recovery(args, name, bundle, snapshot.dtbs(args.orchard, boards), args.output / 'rootfs.json')
        platforms[name] = {'boards': boards, 'layer': files,
                           'boot': {'file': image.name, 'bytes': image.stat().st_size, 'sha256': sha(image)}}
    shutil.copyfile(args.pongo, args.output / 'pongo.bin')
    shutil.rmtree(args.output / '.work', ignore_errors=True)  # recovery and layer staging
    published = write_manifests(args.output, args.release, root, platforms, revision)
    # Assembly provenance is separate from the public installation contract.
    receipt = {'schema': 2, 'release': args.release, 'orchard': revision, 'platforms': platforms,
               'inputs': {name: {'bytes': path.stat().st_size, 'sha256': sha(path)}
                          for name, path in vars(args).items() if isinstance(path, Path) and path.is_file()}}
    (args.output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Public release ready:', published)
    print('Pinned index:', args.output / 'index.toml')


if __name__ == '__main__':
    main()
