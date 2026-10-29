#!/usr/bin/env python3
"""Produce one coherent public release: root, recovery, Pongo and manifest."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from .public_root import build as build_root, sha
from release.manifests import write as write_manifests
from importlib.metadata import version as package_version

PROJECT = Path(__file__).resolve().parents[2]


def resolve_kernel(args):
    """Use an explicit coherent bundle, or Orchard's shared kernel builder."""
    supplied = [getattr(args, name) is not None for name in ('kernel', 'dtb', 'modules_dir')]
    if any(supplied):
        if not all(supplied):
            raise ValueError('Provide --kernel, --dtb and --modules-dir together, or omit all three')
        return
    from orchard_cli.build import configured_device, prepare_kernel
    device = configured_device(PROJECT)
    kernel = prepare_kernel(device=device)
    args.kernel = kernel / 'Image.gz'
    args.dtb = kernel / (device + '.dtb')
    args.modules_dir = kernel / 'lib/modules'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'base-receipt', 'loader', 'pongo', 'busybox', 'dropbear', 'dropbearkey',
                 'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('kernel', 'dtb', 'modules-dir'):
        parser.add_argument('--' + name, type=Path,
                            help='explicit kernel bundle; omit all three kernel inputs to use the Orchard cache')
    parser.add_argument('--release', required=True)
    parser.add_argument('--cleanup-receipt', type=Path, action='append', default=[],
                        help='compatible previous public root receipt for legacy staging cleanup')
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new release output directory')
    # Reject missing distro inputs before a cache miss can start a kernel build.
    for name in ('base', 'base_receipt', 'loader', 'pongo', 'busybox', 'dropbear', 'dropbearkey'):
        if not getattr(args, name).is_file():
            parser.error(f'Missing input file: {getattr(args, name)}')
    for name in ('cursor_tools', 'bluetooth_tools', 'labwc_tools'):
        if not getattr(args, name).is_dir():
            parser.error(f'Missing tools directory: {getattr(args, name)}')
    for receipt in args.cleanup_receipt:
        if not receipt.is_file():
            parser.error(f'Missing cleanup receipt: {receipt}')
    try:
        resolve_kernel(args)
    except ValueError as error:
        parser.error(str(error))
    root = build_root(args.base, args.base_receipt, args.modules_dir, args.dropbear,
                      args.output, args.release, args.cursor_tools, args.bluetooth_tools, args.labwc_tools,
                      kernel=args.kernel, dtb=args.dtb)
    command = [sys.executable, '-m', 'orchard_hardware.image.recovery']
    for name in ('base', 'base_receipt', 'modules_dir', 'loader', 'kernel', 'dtb', 'busybox', 'dropbear', 'dropbearkey'):
        command.extend(['--' + name.replace('_', '-'), str(getattr(args, name))])
    command.extend(['--policy-dir', str(PROJECT / 'image/j71b'),
                    '--root-receipt', str(args.output / 'rootfs.json'),
                    '--output', str(args.output / 'recovery.bin')])
    for receipt in args.cleanup_receipt:
        command.extend(['--cleanup-receipt', str(receipt)])
    subprocess.run(command, check=True)
    shutil.copyfile(args.pongo, args.output / 'pongo.bin')
    assets = {}
    for role, name in (('pongo', 'pongo.bin'), ('recovery', 'recovery.bin'), ('root', 'rootfs.tar.zst')):
        path = args.output / name
        assets[role] = {'file': name, 'bytes': path.stat().st_size, 'sha256': sha(path)}
    assets['root']['expanded_bytes'] = root['expanded_bytes']
    assets['root']['members'] = root['members']
    assets['root']['compression'] = root['compression']
    manifest = {'schema': 1, 'protocol': 1, 'profile': 'j71b', 'release': args.release,
                'qualification': 'pending-fresh-hardware-installation', 'assets': assets}
    published = write_manifests(args.output, args.release, root)
    # Assembly provenance is separate from the public installation contract.
    manifest['hardware_package'] = package_version('orchard-hardware')
    manifest['inputs'] = {name: {'bytes': path.stat().st_size, 'sha256': sha(path)}
                          for name, path in vars(args).items() if isinstance(path, Path) and path.is_file()}
    (args.output / 'build-receipt.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Public release ready:', published)
    print('Pinned index:', args.output / 'index.toml')


if __name__ == '__main__':
    main()
