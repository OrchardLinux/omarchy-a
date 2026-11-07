#!/usr/bin/env python3
"""orchard build's entry (orchard.toml [release]): every component of a release, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY
[--platform NAME ... | --platform all] [--architecture aarch64|armv7h]` in this checkout. A release
has one root of one architecture: the selected platforms' (apple-armv7: armv7h), else
--architecture, else aarch64. Components land in out/components/NAME/KEY/, keyed by the
files they are made from and the architecture, so a build redoes only what changed: a shell edit
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
sys.path.insert(0, str(PROJECT))
from release.architecture import platform_arch, validate  # noqa: E402
DESKTOP_IMAGE = ['desktop/Containerfile', 'desktop/install-toolchain', 'desktop/snapshot_buildenv.py']
# What each component is made from, relative to this checkout.
INPUTS = {
    'desktop': ['desktop/build', 'desktop/build-sources', 'desktop/stage.py', 'desktop/target.py', 'desktop/arm64', 'desktop/armv7', 'desktop/keyboard',
                'desktop/packages', 'desktop/sources.json', 'desktop/upstream.lock', 'desktop/configuration',
                'desktop/greeter', 'desktop/shell', 'desktop/themes', 'release/architecture.py', *DESKTOP_IMAGE],
    'cursor': ['desktop/build-cursor-helper', 'desktop/cursor', 'desktop/target.py', 'release/architecture.py', *DESKTOP_IMAGE],
    'bluetooth': ['desktop/build-bluetooth-tools', 'desktop/bluetooth'],
    'labwc': ['desktop/build-labwc', 'desktop/labwc', 'desktop/target.py', 'desktop/snapshot_buildenv.py',
              'release/architecture.py'],
    'base': ['system/build-rootfs', 'system/assemble-rootfs', 'system/Containerfile',
             'system/install-toolchain', 'system/packages.txt', 'system/rank-mirrors',
             'system/pacman-download', 'release/architecture.py'],
    'artwork': ['boot/build-artwork', 'boot/generate-logo.py', 'boot/splash.py', 'boot/artwork'],
}


# The ARMv7 Arch Linux ARM builder system/build-armv7-builder prepares; it runs ARMv7 code (emulated on arm64).
ARMV7_BUILDER = 'localhost/omarchy-a-arch-builder:armv7h'


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


def targets(orchard, requested, architecture=None):
    """Select one userspace architecture before producing any component."""
    if 'all' in requested and len(requested) != 1:
        raise ValueError('--platform all builds every matching platform and combines with no other')
    explicit = requested if requested != ['all'] else []
    names = list(explicit) if explicit else [p.stem for p in sorted((orchard / 'platforms').glob('*.toml'))]
    found = {name: platform_arch(name, orchard) for name in names}
    selected_arch = validate(architecture or (found[names[0]] if explicit else 'aarch64'))
    if explicit and any(arch != selected_arch for arch in found.values()):
        raise ValueError('A release must use one userspace architecture; build ARMv7 and AArch64 separately')
    selected = [name for name, arch in found.items() if arch == selected_arch]
    if not selected:
        raise ValueError(f'No platforms build the {selected_arch} userspace')
    return selected_arch, selected


def builder_key(image):
    if not image:
        return ''
    if os.environ.get('ORCHARD_BUILD_NATIVE') == '1':
        return 'native:' + image
    return subprocess.check_output(['podman', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', action='append', default=[],
                        help='build this platform (repeat), or all; orchard passes the selection')
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    parser.add_argument('--architecture', choices=('aarch64', 'armv7h'),
                        help="the root's architecture (default: the selected platforms', else aarch64)")
    parser.add_argument('--builder-image', help='prepared Arch Linux ARM desktop/root builder for the selected architecture')
    parser.add_argument('--labwc-builder-image', help='prepared Labwc builder; defaults to --builder-image')
    args = parser.parse_args()
    orchard = args.orchard or (Path(os.environ['ORCHARD_CHECKOUT']) if os.environ.get('ORCHARD_CHECKOUT') else None)
    if orchard is None or not (orchard / 'src/orchard').is_dir():
        parser.error('Name the orchard snapshot: --orchard DIR, or ORCHARD_CHECKOUT (orchard build sets it)')
    # Every step below, the desktop recipes included, finds orchard here.
    os.environ['ORCHARD_CHECKOUT'] = str(orchard.resolve())
    try:
        architecture, platforms = targets(orchard, args.platform, args.architecture)
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))
    # orchard.inputs resolves every arm64 platform when it is given none; the 32-bit ones are named.
    named = [name for name in args.platform if name != 'all'] or ([] if architecture == 'aarch64' else platforms)
    selected = [part for name in named for part in ('--platform', name)]
    target_args = ['--architecture', architecture]
    if architecture == 'armv7h' and not args.builder_image:
        args.builder_image = ARMV7_BUILDER  # what system/build-armv7-builder prepares
    builder_args = ['--builder-image', args.builder_image] if args.builder_image else []
    labwc_image = args.labwc_builder_image or args.builder_image
    labwc_args = ['--builder-image', labwc_image] if labwc_image else []
    identity = builder_key(args.builder_image)
    compiler_identity = builder_key(labwc_image)

    desktop, desktop_key = component(PROJECT, 'desktop', INPUTS['desktop'],
        lambda path, work: python('desktop/build', '--output', path, *target_args, *builder_args),
        artifact='desktop', extra=[architecture, identity])
    cursor, _ = component(PROJECT, 'cursor', INPUTS['cursor'],
                          lambda path, work: python('desktop/build-cursor-helper', '--output', path,
                                                    *target_args, *builder_args),
                          artifact='cursor-tools', extra=[architecture, identity])
    bluetooth, _ = component(PROJECT, 'bluetooth', INPUTS['bluetooth'],
                             lambda path, work: python('desktop/build-bluetooth-tools', '--output', path),
                             artifact='bluetooth-tools')
    labwc, _ = component(PROJECT, 'labwc', INPUTS['labwc'],
                         lambda path, work: python('desktop/build-labwc', '--output', path, *target_args, *labwc_args),
                         artifact='labwc-tools', extra=[architecture, compiler_identity])
    # The base names the component, not a release: it serves every build with the same inputs.
    base, _ = component(PROJECT, 'base', INPUTS['base'],
                        lambda path, work: run('system/build-rootfs', '--output', path, '--desktop', desktop,
                                               '--release', 'base-' + desktop_key[:16], *target_args, *builder_args),
                        artifact='base', extra=[desktop_key, architecture, identity])
    # The Omarchy mark: the splash of the root, the logo of the release.
    artwork, _ = component(PROJECT, 'artwork', INPUTS['artwork'],
                           lambda path, work: python('boot/build-artwork', '--output', path), artifact='artwork')
    # What orchard supplies finished: kernels, loaders, tools (the nightly's when they match).
    inputs = PROJECT / f'out/components/.inputs-{architecture}.json'
    orchard_command('orchard.inputs', '--output', inputs, *selected)
    tools = json.loads(inputs.read_text())['shared']['tools']
    python('-m', 'release.build', '--release', args.version, '--inputs', inputs,
           '--base', base / 'rootfs.tar.gz', '--base-receipt', base / 'rootfs.tar.gz.json',
           '--splash', artwork / 'splash', '--logo', artwork / 'logo.bin',
           *(part for name in ('busybox', 'dropbear', 'dropbearkey')
             for part in ('--' + name, tools[name])),
           '--cursor-tools', cursor, '--bluetooth-tools', bluetooth, '--labwc-tools', labwc,
           *target_args, '--output', args.output)
    python('-m', 'release.audit', args.output / 'release.toml')
    # install.sh and orchard-install.pyz, with orchard's launch loaders.
    orchard_command('orchard.installer', 'release', args.output)


if __name__ == '__main__':
    main()
