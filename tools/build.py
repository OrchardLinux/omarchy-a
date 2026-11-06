#!/usr/bin/env python3
"""orchard build's entry (orchard.toml [release]): every component of a release, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY
[--platform NAME ... | --platform all]` in this checkout. Components land in out/components/NAME/KEY/, keyed by the
files they are made from, so a build redoes only what changed: a shell edit
rebuilds the desktop payload and the root, not Labwc. orchard supplies its
m1n1, Pongo, the static tools and every platform's kernel
(python -m orchard.inputs); its producers run as commands from the orchard
snapshot (ORCHARD_CHECKOUT, which orchard build sets, or --orchard DIR) and
none of its Python is imported (orchard docs/distribution-contract.md). The
release itself is always assembled anew.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from components import component  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
DESKTOP_IMAGE = ['desktop/Containerfile', 'desktop/install-toolchain']
# What each component is made from, relative to this checkout.
INPUTS = {
    'desktop': ['desktop/build', 'desktop/build-sources', 'desktop/stage.py', 'desktop/arm64', 'desktop/keyboard',
                'desktop/packages', 'desktop/sources.json', 'desktop/upstream.lock', 'desktop/configuration',
                'desktop/greeter', 'desktop/shell', 'desktop/themes', *DESKTOP_IMAGE],
    'cursor': ['desktop/build-cursor-helper', 'desktop/cursor', *DESKTOP_IMAGE],
    'bluetooth': ['desktop/build-bluetooth-tools', 'desktop/bluetooth'],
    'labwc': ['desktop/build-labwc', 'desktop/labwc'],
    'base': ['system/build-rootfs', 'system/assemble-rootfs', 'system/Containerfile',
             'system/install-toolchain', 'system/packages.txt'],
    'artwork': ['boot/build-artwork', 'boot/generate-logo.py', 'boot/splash.py', 'boot/artwork'],
}


def run(*argv):
    print('+', ' '.join(map(str, argv)), flush=True)
    subprocess.run([str(part) for part in argv], cwd=PROJECT, check=True)


def python(*argv):
    run(sys.executable, *argv)


def orchard_command(module, *argv):
    """orchard's producer MODULE as a command from the snapshot (PYTHONPATH=SNAPSHOT/src)."""
    root = Path(os.environ['ORCHARD_CHECKOUT'])
    print('+', sys.executable, '-m', module, ' '.join(map(str, argv)), flush=True)
    subprocess.run([sys.executable, '-m', module, *map(str, argv)], cwd=PROJECT, check=True,
                   env={**os.environ, 'PYTHONPATH': str(root / 'src')})


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', action='append', default=[],
                        help='build this platform (repeat), or all; orchard passes the selection')
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    args = parser.parse_args()
    orchard = args.orchard or (Path(os.environ['ORCHARD_CHECKOUT']) if os.environ.get('ORCHARD_CHECKOUT') else None)
    if orchard is None or not (orchard / 'src/orchard').is_dir():
        parser.error('Name the orchard snapshot: --orchard DIR, or ORCHARD_CHECKOUT (orchard build sets it)')
    # Every step below, the desktop recipes included, finds orchard here.
    os.environ['ORCHARD_CHECKOUT'] = str(orchard.resolve())
    if 'all' in args.platform and len(args.platform) > 1:
        parser.error('--platform all builds every platform and combines with no other')
    # orchard.inputs resolves every platform when it is given none.
    selected = [part for name in args.platform if name != 'all' for part in ('--platform', name)]

    desktop, desktop_key = component(PROJECT, 'desktop', INPUTS['desktop'],
        lambda path, work: python('desktop/build', '--output', path), artifact='desktop')
    cursor, _ = component(PROJECT, 'cursor', INPUTS['cursor'],
                          lambda path, work: python('desktop/build-cursor-helper', '--output', path),
                          artifact='cursor-tools')
    bluetooth, _ = component(PROJECT, 'bluetooth', INPUTS['bluetooth'],
                             lambda path, work: python('desktop/build-bluetooth-tools', '--output', path),
                             artifact='bluetooth-tools')
    labwc, _ = component(PROJECT, 'labwc', INPUTS['labwc'],
                         lambda path, work: python('desktop/build-labwc', '--output', path),
                         artifact='labwc-tools')
    # The base names the component, not a release: it serves every build with the same inputs.
    base, _ = component(PROJECT, 'base', INPUTS['base'],
                        lambda path, work: run('system/build-rootfs', '--output', path, '--desktop', desktop,
                                               '--release', 'base-' + desktop_key[:16]),
                        artifact='base', extra=[desktop_key])
    # The Omarchy mark is data for orchard's m1n1, which every distribution boots.
    artwork, _ = component(PROJECT, 'artwork', INPUTS['artwork'],
                           lambda path, work: python('boot/build-artwork', '--output', path), artifact='artwork')
    # What orchard supplies finished: kernels, m1n1, Pongo, tools (the nightly's when they match).
    inputs = PROJECT / 'out/components/.inputs.json'
    orchard_command('orchard.inputs', '--output', inputs, *selected)
    shared = json.loads(inputs.read_text())['shared']
    tools = shared['tools']
    python('-m', 'release.build', '--release', args.version, '--inputs', inputs,
           '--base', base / 'rootfs.tar.gz', '--base-receipt', base / 'rootfs.tar.gz.json',
           '--splash', artwork / 'splash', '--logo', artwork / 'logo.bin',
           *(part for name in ('busybox', 'dropbear', 'dropbearkey')
             for part in ('--' + name, tools[name])),
           '--cursor-tools', cursor, '--bluetooth-tools', bluetooth, '--labwc-tools', labwc,
           '--output', args.output)
    python('-m', 'release.audit', args.output / 'release.toml')
    # install.sh and orchard-install.pyz, with orchard's launch loaders.
    orchard_command('orchard.installer', 'release', args.output)


if __name__ == '__main__':
    main()
