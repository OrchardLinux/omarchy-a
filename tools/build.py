#!/usr/bin/env python3
"""orchard build's entry (orchard.toml [release]): every component of a release, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY
[--platform NAME ... | --platform all]` in this checkout. Components land in out/components/NAME/KEY/, keyed by the
files they are made from, so a build redoes only what changed: a shell edit
rebuilds the desktop payload and the root, not Labwc. orchard supplies its
m1n1, Pongo, the static recovery tools and every platform's kernel
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
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from components import component  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from release.architecture import platform_arch, validate  # noqa: E402
from release.build import TOOLS, platform_inputs, require_native_contract, selected_root_format  # noqa: E402
from release.provenance import producer_identity  # noqa: E402
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


def device_platform(orchard, device):
    if '/' in device or device in ('', '.', '..'):
        raise ValueError('Invalid device name')
    path = orchard / 'devices' / device / 'device.toml'
    return tomllib.loads(path.read_text())['kernel']['platform']


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', action='append', default=[],
                        help='build this platform (repeat), or all; orchard passes the selection')
    parser.add_argument('--device', help='board whose loader and calibration inputs the recovery uses')
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    parser.add_argument('--architecture', choices=('aarch64', 'armv7h'), help='userspace architecture; inferred from an explicit platform')
    parser.add_argument('--builder-image', help='prepared Arch Linux ARM desktop/root builder for the selected architecture')
    parser.add_argument('--labwc-builder-image', help='prepared Labwc builder; defaults to --builder-image')
    parser.add_argument('--platform-loader', action='append', default=[], metavar='PLATFORM=FILE')
    parser.add_argument('--platform-tools', action='append', default=[], metavar='PLATFORM=DIRECTORY')
    parser.add_argument('--platform-lwvm', action='append', default=[], metavar='PLATFORM=FILE')
    args = parser.parse_args()
    orchard = args.orchard or (Path(os.environ['ORCHARD_CHECKOUT']) if os.environ.get('ORCHARD_CHECKOUT') else None)
    if orchard is None or not (orchard / 'src/orchard').is_dir():
        parser.error('Name the orchard snapshot: --orchard DIR, or ORCHARD_CHECKOUT (orchard build sets it)')
    # Every producer below resolves Orchard from this exact snapshot.
    os.environ['ORCHARD_CHECKOUT'] = str(orchard.resolve())
    try:
        requested = args.platform
        if args.device:
            board_platform = device_platform(orchard, args.device)
            if requested and requested != [board_platform]:
                raise ValueError('--device must select its own platform')
            requested = [board_platform]
        architecture, platforms = targets(orchard, requested, args.architecture)
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))
    selected = [part for name in platforms for part in ('--platform', name)]
    if architecture == 'armv7h':
        if not args.device:
            parser.error('Select one ARMv7 board with --device before resolving its build inputs')
        # The CLI check precedes cold-cache kernel, loader and helper production.
        require_native_contract(orchard, lwvm_required=any(
            selected_root_format(orchard, name, args.device) == 'lwvm' for name in platforms))
    producer = producer_identity(orchard, PROJECT)
    producer_key = json.dumps(producer, sort_keys=True)
    # Resolve native storage helpers before any desktop or root compilation.
    inputs = PROJECT / f'out/components/.inputs-{architecture}.json'
    overrides = [part for option in ('platform_loader', 'platform_tools', 'platform_lwvm')
                 for value in getattr(args, option)
                 for part in ('--' + option.replace('_', '-'), value)]
    board = ['--device', args.device] if args.device else []
    orchard_command('orchard.inputs', '--output', inputs, *selected, *board, *overrides)
    document = json.loads(inputs.read_text())
    shared = document.get('shared', {})
    preflight = argparse.Namespace(architecture=architecture, device=args.device, orchard=orchard,
                                  loader=shared.get('m1n1'),
                                  **{key: shared.get('tools', {}).get(key) for key in TOOLS})
    components = {name: platform_inputs(preflight, name, document) for name in platforms}
    if architecture == 'armv7h':
        require_native_contract(orchard, components)
    target_args = ['--architecture', architecture]
    builder_args = ['--builder-image', args.builder_image] if args.builder_image else []
    labwc_image = args.labwc_builder_image or args.builder_image
    labwc_args = ['--builder-image', labwc_image] if labwc_image else []
    identity = builder_key(args.builder_image)
    compiler_identity = builder_key(labwc_image)

    desktop, desktop_key = component(PROJECT, 'desktop', INPUTS['desktop'],
        lambda path, work: python('desktop/build', '--output', path, *target_args, *builder_args),
        artifact='desktop', extra=[architecture, identity, producer_key])
    cursor, cursor_key = component(PROJECT, 'cursor', INPUTS['cursor'],
                          lambda path, work: python('desktop/build-cursor-helper', '--output', path, *target_args, *builder_args),
                          artifact='cursor-tools', extra=[architecture, identity, producer_key])
    bluetooth, bluetooth_key = component(PROJECT, 'bluetooth', INPUTS['bluetooth'],
                             lambda path, work: python('desktop/build-bluetooth-tools', '--output', path),
                             artifact='bluetooth-tools')
    labwc, labwc_key = component(PROJECT, 'labwc', INPUTS['labwc'],
                         lambda path, work: python('desktop/build-labwc', '--output', path, *target_args, *labwc_args),
                         artifact='labwc-tools', extra=[architecture, compiler_identity, producer_key])
    # The base names the component, not a release: it serves every build with the same inputs.
    base, base_key = component(PROJECT, 'base', INPUTS['base'],
                        lambda path, work: run('system/build-rootfs', '--output', path, '--desktop', desktop,
                                               '--release', 'base-' + desktop_key[:16], *target_args, *builder_args),
                        artifact='base', extra=[desktop_key, architecture, identity])
    # The artwork serves the AArch64 m1n1 flow and the shared root's splash.
    artwork, artwork_key = component(PROJECT, 'artwork', INPUTS['artwork'],
                           lambda path, work: python('boot/build-artwork', '--output', path), artifact='artwork')
    keys = PROJECT / f'out/components/.keys-{architecture}.json'
    keys.parent.mkdir(parents=True, exist_ok=True)
    keys.write_text(json.dumps({'schema': 1, 'architecture': architecture, 'producer': producer, 'components': {
        'desktop': desktop_key, 'cursor': cursor_key, 'bluetooth': bluetooth_key,
        'labwc': labwc_key, 'base': base_key, 'artwork': artwork_key}}, indent=2) + '\n')
    first = document['platforms'][platforms[0]]
    tools = first.get('tools') or shared['tools']
    loader = first.get('loader', {}).get('file') or shared['m1n1']
    access_tools = ('busybox', 'dropbear', 'dropbearkey')
    native_inputs = [part for name in access_tools for part in ('--' + name, tools[name])]
    if architecture == 'armv7h':
        native_inputs += ['--loader', loader]
        native_inputs += [part for name in ('wpa_supplicant', 'wpa_cli', 'iw')
                          for part in ('--' + name.replace('_', '-'), tools[name])]
    python('-m', 'release.build', '--release', args.version, '--inputs', inputs,
           '--base', base / 'rootfs.tar.gz', '--base-receipt', base / 'rootfs.tar.gz.json',
           '--base-release', 'base-' + desktop_key[:16], '--component-keys', keys,
           '--splash', artwork / 'splash', '--logo', artwork / 'logo.bin', *native_inputs,
           '--cursor-tools', cursor, '--bluetooth-tools', bluetooth, '--labwc-tools', labwc,
           *target_args, *selected, '--output', args.output)
    python('-m', 'release.audit', args.output / 'release.toml')
    # The public installer currently implements the ARM64 m1n1 boot method.
    if architecture == 'aarch64':
        orchard_command('orchard.installer', 'release', args.output)


if __name__ == '__main__':
    main()
