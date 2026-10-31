#!/usr/bin/env python3
"""orchard build's entry (distro.toml): every component of a release, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY` in
this checkout. Components land in out/components/NAME/KEY/, keyed by the
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
from orchard.build import prepare_shared, recipe_key
from orchard.hardware import ROOT as ORCHARD

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
    'loader': ['boot/build-loader', 'boot/generate-logo.py', 'boot/artwork', 'boot/m1n1'],
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
    args = parser.parse_args()

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
    loader, _ = component(PROJECT, 'loader', INPUTS['loader'],
                          lambda path, work: python('boot/build-loader', '--output', path, '--work-dir', work / 'm1n1'),
                          artifact='m1n1.bin', extra=[recipe_key(ORCHARD, ['boot/m1n1', 'src/orchard/buildenv.py'])])
    shared = prepare_shared()
    tools = shared['tools']
    python('-m', 'release.build', '--release', args.version,
           '--base', base / 'rootfs.tar.gz', '--base-receipt', base / 'rootfs.tar.gz.json',
           '--loader', loader, '--pongo', shared['pongo'],
           '--busybox', tools / 'busybox', '--dropbear', tools / 'dropbear', '--dropbearkey', tools / 'dropbearkey',
           '--wpa-supplicant', tools / 'wpa_supplicant', '--wpa-cli', tools / 'wpa_cli', '--iw', tools / 'iw',
           '--cursor-tools', cursor, '--bluetooth-tools', bluetooth, '--labwc-tools', labwc,
           '--output', args.output)
    python('-m', 'release.audit', args.output / 'release.toml')
    # install.sh and orchard-install.pyz, with orchard's launch loaders from its cache.
    python('-m', 'orchard.installer', 'release', args.output)


if __name__ == '__main__':
    main()
