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
from release.manifests import write as write_manifests


def kernels(args):
    """{platform: staged kernel bundle}: explicit --kernel-dir, else orchard's cache."""
    from orchard.image import platform
    known = platform.platforms()
    explicit = {}
    for value in args.kernel_dir or ():
        name, separator, path = value.partition('=')
        if not separator or name not in known:
            raise ValueError(f'Use --kernel-dir PLATFORM=DIRECTORY with a platform of: {", ".join(known)}')
        explicit[name] = Path(path)
    selected = args.platform or known
    unknown = sorted(set(selected) - set(known))
    if unknown:
        raise ValueError(f'Unknown platform {", ".join(unknown)}; known: {", ".join(known)}')
    return {name: explicit.get(name) or platform.kernel(name) for name in selected}


def recovery(args, name, bundle, root_receipt):
    """The platform's RAM recovery, which starts every board of it; m1n1 picks the DTB."""
    from orchard.image import platform
    dtbs = [bundle / 'dtbs' / (dtb + '.dtb') for dtb in sorted(set(platform.boards(name).values()))]
    missing = [path.name for path in dtbs if not path.is_file()]
    if missing:
        raise ValueError(f'The {name} kernel bundle lacks device DTBs: ' + ', '.join(missing))
    output = args.output / f'recovery-{name}.bin'
    command = [sys.executable, '-m', 'orchard.image.recovery', *(f'--dtb={path}' for path in dtbs)]
    for option in ('base', 'base_receipt', 'loader', 'busybox', 'dropbear', 'dropbearkey',
                   'wpa_supplicant', 'wpa_cli', 'iw'):
        command.extend(['--' + option.replace('_', '-'), str(getattr(args, option))])
    command.extend(['--kernel', str(bundle / 'Image.gz'), '--modules-dir', str(bundle / 'lib/modules'),
                    '--root-receipt', str(root_receipt), '--output', str(output)])
    subprocess.run(command, check=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for name in ('base', 'base-receipt', 'loader', 'pongo', 'busybox', 'dropbear', 'dropbearkey',
                 'wpa-supplicant', 'wpa-cli', 'iw', 'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--kernel-dir', action='append', metavar='PLATFORM=DIRECTORY',
                        help="a platform's staged kernel bundle; repeat; others come from orchard's cache")
    parser.add_argument('--platform', action='append',
                        help='only this platform (repeat); for development, a release covers every platform')
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new release output directory')
    # Reject missing distro inputs before a cache miss can start a kernel build.
    for name in ('base', 'base_receipt', 'loader', 'pongo', 'busybox', 'dropbear', 'dropbearkey',
                 'wpa_supplicant', 'wpa_cli', 'iw'):
        if not getattr(args, name).is_file():
            parser.error(f'Missing input file: {getattr(args, name)}')
    for name in ('cursor_tools', 'bluetooth_tools', 'labwc_tools'):
        if not getattr(args, name).is_dir():
            parser.error(f'Missing tools directory: {getattr(args, name)}')
    try:
        bundles = kernels(args)
    except ValueError as error:
        parser.error(str(error))
    from orchard import hardware
    from orchard.image import platform
    root = build_root(args.base, args.base_receipt, args.output, args.release,
                      args.cursor_tools, args.bluetooth_tools, args.labwc_tools,
                      tools={'dropbear': args.dropbear, 'dropbearkey': args.dropbearkey, 'busybox': args.busybox})
    platforms = {}
    for name, bundle in bundles.items():
        layer = platform.build(name, args.output, bundle=bundle, busybox=args.busybox)
        image = recovery(args, name, bundle, args.output / 'rootfs.json')
        platforms[name] = {'boards': layer.pop('boards'), 'layer': layer,
                           'boot': {'file': image.name, 'bytes': image.stat().st_size, 'sha256': sha(image)}}
    shutil.copyfile(args.pongo, args.output / 'pongo.bin')
    shutil.rmtree(args.output / '.work', ignore_errors=True)  # recovery staging
    revision = hardware.revision()
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
