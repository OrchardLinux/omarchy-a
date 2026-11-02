#!/usr/bin/env python3
"""orchard build's entry (distro.toml): every component of a release, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY
[--platform NAME ... | --platform all]` in this checkout. Components land in out/components/NAME/KEY/, keyed by the
files they are made from, so a build redoes only what changed: a shell edit
rebuilds the desktop payload and the root, not Labwc. orchard supplies
Pongo, the static recovery tools and every platform's kernel from its
shared cache. The release itself is always assembled anew.
"""
import argparse
from pathlib import Path
import subprocess
import sys

from orchard.distro import component
from orchard.build import prepare_shared

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


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', action='append', default=[],
                        help='build this platform (repeat), or all; orchard passes the selection')
    args = parser.parse_args()
    if 'all' in args.platform and len(args.platform) > 1:
        parser.error('--platform all builds every platform and combines with no other')
    # The release builder builds every platform when it is given none.
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
    shared = prepare_shared()
    tools = shared['tools']
    python('-m', 'release.build', '--release', args.version,
           '--base', base / 'rootfs.tar.gz', '--base-receipt', base / 'rootfs.tar.gz.json',
           '--loader', shared['loader'], '--splash', artwork / 'splash', '--logo', artwork / 'logo.bin',
           '--pongo', shared['pongo'],
           '--busybox', tools / 'busybox', '--dropbear', tools / 'dropbear', '--dropbearkey', tools / 'dropbearkey',
           '--wpa-supplicant', tools / 'wpa_supplicant', '--wpa-cli', tools / 'wpa_cli', '--iw', tools / 'iw',
           '--cursor-tools', cursor, '--bluetooth-tools', bluetooth, '--labwc-tools', labwc,
           *selected, '--output', args.output)
    python('-m', 'release.audit', args.output / 'release.toml')
    # install.sh and orchard-install.pyz, with orchard's launch loaders from its cache.
    python('-m', 'orchard.installer', 'release', args.output)


if __name__ == '__main__':
    main()
