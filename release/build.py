#!/usr/bin/env python3
"""Build an architecture-specific root and consume Orchard's matching installation contract.

Orchard's platform layer supplies the kernel, DTBs and modules. AArch64 uses
its platform index and block-image producer. ARMv7 builds a selected board's
native layer and recovery from the same kernel bundle.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tomllib

from .public_root import build as build_root, sha
from release import snapshot
from release.manifests import write as write_manifests
from release.architecture import validate, platform_arch, orchard_arch, check_elf
from .common import PROJECT
from .provenance import component_receipt, file_receipt, source_identity, orchard_identity, producer_identity, input_revision


TOOLS = ('busybox', 'dropbear', 'dropbearkey', 'wpa_supplicant', 'wpa_cli', 'iw')


def orchard_files(args):
    """Take ARM64 platform layers and block-image install tools from Orchard's index."""
    source = ('--release', args.orchard_release) if args.orchard_release else ('--inputs', args.inputs)
    selection = [part for name in (args.platform or ()) for part in ('--platform', name)] if args.orchard_release else []
    snapshot.command(args.orchard, 'orchard.image.platforms_index', args.output, *source,
                     *selection, stdout=subprocess.DEVNULL)
    return tomllib.loads((args.output / 'platforms.toml').read_text())


def check_static_elf(path, architecture, label='helper'):
    """Check a native helper before assembling a root that depends on it."""
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError(f'{label}: static helper exceeds its inspection bound')
    data = path.read_bytes()
    check_elf(data, architecture, label)
    arm = data[4] == 1
    offset = struct.unpack_from('<I' if arm else '<Q', data, 28 if arm else 32)[0]
    size, count = struct.unpack_from('<HH', data, 42 if arm else 54)
    if not count or size != (32 if arm else 56) or offset + size * count > len(data):
        raise ValueError(f'{label}: invalid ELF program headers')
    loadable = False
    for index in range(count):
        start = offset + index * size
        kind = struct.unpack_from('<I', data, start)[0]
        loadable |= kind == 1
        if kind == 3:
            raise ValueError(f'{label}: static helper has an ELF interpreter')
        if kind != 2:
            continue
        dynamic = struct.unpack_from('<I' if arm else '<Q', data, start + (4 if arm else 8))[0]
        length = struct.unpack_from('<I' if arm else '<Q', data, start + (16 if arm else 32))[0]
        stride = 8 if arm else 16
        if not length or length % stride or dynamic + length > len(data):
            raise ValueError(f'{label}: invalid ELF dynamic segment')
        for position in range(dynamic, dynamic + length, stride):
            tag = struct.unpack_from('<I' if arm else '<Q', data, position)[0]
            if tag == 0:
                break
            if tag == 1:
                raise ValueError(f'{label}: static helper needs a shared library')
        else:
            raise ValueError(f'{label}: unterminated ELF dynamic segment')
    if not loadable:
        raise ValueError(f'{label}: static helper has no loadable segment')
    return architecture


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
    architecture = validate(getattr(args, 'architecture', 'aarch64'))
    declared = (document or {}).get('architecture')
    if declared is not None and declared != orchard_arch(architecture):
        raise ValueError('Input document architecture differs from the root architecture')
    for name in selected:
        if platform_arch(name, getattr(args, 'orchard', None)) != architecture:
            raise ValueError(f'{name}: platform architecture differs from {architecture} root')
        declared = offered.get(name, {}).get('architecture')
        if declared is not None and declared != orchard_arch(architecture):
            raise ValueError(f'{name}: input architecture differs from {architecture} root')
    return {name: explicit.get(name) or Path(offered[name]['kernel']) for name in selected}


def require_native_contract(orchard, components=None, *, lwvm_required=False):
    """Check the selected snapshot's public commands before compiling a native root."""
    components = components or {}
    options = {
        'orchard.image.platform': {'--root-architecture', '--device'},
        'orchard.image.recovery': {'--platform', '--device'},
    }
    if lwvm_required or any(getattr(component, 'lwvm', None) is not None for component in components.values()):
        options['orchard.image.platform'].update(('--lwvm', '--rescue-tools'))
        options['orchard.image.recovery'].add('--lwvm')
    for module, required in options.items():
        try:
            result = snapshot.command(orchard, module, '--help', capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError(f'Orchard native producer is unavailable: {module}') from error
        offered = set(re.findall(r'--[a-z][a-z0-9-]*', result.stdout))
        missing = sorted(required - offered)
        if missing:
            raise ValueError(f'{module} lacks the native root contract ({", ".join(missing)}); '
                             'use Orchard with the installed-root and recovery producers')


def selected_root_format(orchard, platform, device):
    """The snapshot's root format for a selected board."""
    described = tomllib.loads((Path(orchard) / 'platforms' / (platform + '.toml')).read_text()).get('root', {})
    result = described.get('format', 'gpt')
    if described.get('devices') is not None and device not in described['devices']:
        result = 'gpt'
    if result not in ('gpt', 'lwvm'):
        raise ValueError(f'{platform}: unsupported root format {result}')
    return result


def platform_inputs(args, name, document=None):
    """Resolve the loader/tools of NAME without borrowing another ISA's shared inputs."""
    resolved = copy.copy(args)
    architecture = getattr(args, 'architecture', 'aarch64')
    row = (document or {}).get('platforms', {}).get(name, {})
    boards = row.get('boards', {})
    requested_device = getattr(args, 'device', None)
    if requested_device is not None and boards and requested_device not in boards:
        raise ValueError(f'{name}: input boards differ from the selected device {requested_device}')
    resolved.device = next(iter(boards)) if len(boards) == 1 else getattr(args, 'device', None)
    if architecture == 'armv7h' and (len(boards) != 1 or not resolved.device):
        raise ValueError(f'{name}: Cascadia requires one selected board in the input record or --device')
    loader = row.get('loader', {})
    expected_loader = 'cascadia' if architecture == 'armv7h' else 'm1n1'
    if loader and (not isinstance(loader, dict) or loader.get('kind') != expected_loader):
        raise ValueError(f'{name}: incompatible loader kind')
    if loader:
        resolved.loader = Path(loader['file'])
    for tool in TOOLS:
        value = row.get('tools', {}).get(tool, getattr(args, tool, None))
        if value is None:
            raise ValueError(f'{name}: missing {architecture} tool {tool}')
        setattr(resolved, tool, Path(value))
    if getattr(resolved, 'loader', None) is None:
        raise ValueError(f'{name}: missing {expected_loader} loader')
    resolved.kernel_image = row.get('image', 'zImage' if architecture == 'armv7h' else 'Image.gz')
    if resolved.kernel_image != ('zImage' if architecture == 'armv7h' else 'Image.gz'):
        raise ValueError(f'{name}: kernel image differs from {architecture} platform')
    for field in ('loader', *TOOLS):
        path = getattr(resolved, field)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'{name}: missing regular component {field}: {path}')
    if architecture == 'armv7h':
        for tool in TOOLS:
            check_static_elf(getattr(resolved, tool), architecture, name + ' ' + tool)
    root_format = row.get('root_format', 'gpt')
    if root_format not in ('gpt', 'lwvm'):
        raise ValueError(f'{name}: unsupported root format {root_format}')
    orchard = getattr(args, 'orchard', None)
    if orchard is not None and root_format != selected_root_format(orchard, name, resolved.device):
        raise ValueError(f'{name}: input root format differs from the selected board')
    helper = row.get('tools', {}).get('lwvm', getattr(args, 'lwvm', None))
    resolved.lwvm = Path(helper) if helper is not None else None
    if root_format == 'lwvm' and resolved.lwvm is None:
        raise ValueError(f'{name}: LwVM root requires tools.lwvm')
    if resolved.lwvm is not None:
        if resolved.lwvm.is_symlink() or not resolved.lwvm.is_file():
            raise ValueError(f'{name}: missing regular LwVM helper: {resolved.lwvm}')
        check_static_elf(resolved.lwvm, architecture, name + ' LwVM helper')
        if (resolved.dropbear.name != 'dropbear' or resolved.dropbearkey.name != 'dropbearkey' or
                resolved.dropbear.parent != resolved.dropbearkey.parent):
            raise ValueError(f'{name}: LwVM rescue tools require one Dropbear directory')
    return resolved


def layer(args, name, bundle):
    """orchard's platform layer of NAME (orchard.image.platform), and its receipt."""
    receipt = args.output / '.work' / f'platform-{name}.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    snapshot.command(args.orchard, 'orchard.image.platform', name, '--output', args.output, '--kernel-dir', bundle,
                     '--busybox', args.busybox, '--root-architecture', orchard_arch(args.architecture),
                     *(['--lwvm', args.lwvm, '--rescue-tools', args.dropbear.parent]
                       if getattr(args, 'lwvm', None) is not None else []),
                     *(['--device', args.device] if getattr(args, 'device', None) else []),
                     '--receipt', receipt, stdout=subprocess.DEVNULL)
    return json.loads(receipt.read_text())


def recovery(args, name, bundle, boards, root_receipt):
    """The platform's RAM recovery, which starts every board of it; m1n1 picks the DTB."""
    dtbs = [bundle / 'dtbs' / (dtb + '.dtb') for dtb in sorted(set(boards.values()))]
    missing = [path.name for path in dtbs if not path.is_file()]
    if missing:
        raise ValueError(f'The {name} kernel bundle lacks device DTBs: ' + ', '.join(missing))
    output = args.output / f'recovery-{name}.bin'
    command = [*(f'--dtb={path}' for path in dtbs)]
    if args.architecture == 'armv7h':
        command.extend(['--platform', name])
        if getattr(args, 'device', None):
            command.extend(['--device', args.device])
    for option in ('base', 'base_receipt', 'loader', 'busybox', 'dropbear', 'dropbearkey',
                   'wpa_supplicant', 'wpa_cli', 'iw'):
        command.extend(['--' + option.replace('_', '-'), str(getattr(args, option))])
    if args.architecture == 'aarch64':
        command.extend(['--logo', str(args.logo)])
    if getattr(args, 'lwvm', None) is not None:
        command.extend(['--lwvm', str(args.lwvm)])
    command.extend(['--kernel', str(bundle / args.kernel_image), '--modules-dir', str(bundle / 'lib/modules'),
                    '--root-receipt', str(root_receipt), '--output', str(output)])
    snapshot.command(args.orchard, 'orchard.image.recovery', *command)
    return output


def consumed_files(args, components, bundles):
    paths = {name: path for name, path in vars(args).items()
             if isinstance(path, Path) and (path.is_file() or path.is_symlink())}
    for name, component in components.items():
        for role in ('loader', *TOOLS, 'lwvm'):
            path = getattr(component, role, None)
            if path is not None:
                paths[f'platforms.{name}.{role}'] = path
    for name, bundle in bundles.items():
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                paths[f'kernel.{name}.{path.relative_to(bundle).as_posix()}'] = path
    return {name: file_receipt(path) for name, path in sorted(paths.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    for name in ('base', 'base-receipt', 'splash', 'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('loader', 'logo', 'pongo', 'busybox', 'dropbear', 'dropbearkey', 'wpa-supplicant', 'wpa-cli', 'iw', 'lwvm'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--architecture', choices=('aarch64', 'armv7h'), default='aarch64')
    parser.add_argument('--device', help='board profile when explicit ARMv7 components are used without an inputs record')
    parser.add_argument('--base-release', help='expected release stamp of the cached base component')
    parser.add_argument('--component-keys', type=Path, help='cache keys supplied by tools/build.py')
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    origin = parser.add_mutually_exclusive_group()
    origin.add_argument('--orchard-release', metavar='TAG', help='take ARM64 platform files from this Orchard build')
    origin.add_argument('--inputs', type=Path, help="orchard's selected inputs for this build (python -m orchard.inputs)")
    parser.add_argument('--kernel-dir', action='append', metavar='PLATFORM=DIRECTORY',
                        help="a platform's staged kernel bundle; repeat; others come from --inputs")
    parser.add_argument('--platform', action='append',
                        help='only this platform (repeat); for development, a release covers every platform')
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('Choose a new release output directory')
    # Reject missing distro inputs before anything is assembled.
    required = ('base', 'base_receipt', 'splash')
    if args.architecture == 'aarch64':
        required += ('logo', 'busybox', 'dropbear', 'dropbearkey')
    for name in required:
        if getattr(args, name) is None or not getattr(args, name).is_file():
            parser.error(f'Missing input file: {getattr(args, name)}')
    for name in ('cursor_tools', 'bluetooth_tools', 'labwc_tools'):
        if not getattr(args, name).is_dir():
            parser.error(f'Missing tools directory: {getattr(args, name)}')
    initial_arguments = consumed_files(args, {}, {})
    try:
        args.orchard = snapshot.directory(args.orchard)
        document = json.loads(args.inputs.read_text()) if args.inputs else None
        orchard_source = orchard_identity(args.orchard)
        producer = producer_identity(args.orchard, PROJECT)
        revision = input_revision(orchard_source, document.get('orchard', {}) if document is not None else None)
        if args.architecture == 'aarch64':
            if args.inputs is None and args.orchard_release is None:
                raise ValueError('Name --inputs or --orchard-release for the ARM64 platform index')
            if args.kernel_dir:
                raise ValueError('Put explicit ARM64 kernels in the selected --inputs document')
            if document is not None:
                selected = kernels(args, document)
                if set(selected) != set(document['platforms']):
                    raise ValueError('Create a selected --inputs document before building an ARM64 platform subset')
            components, bundles = {}, {}
        else:
            if args.orchard_release is not None:
                raise ValueError('ARMv7 requires selected --inputs; the platform index serves ARM64')
            if document is None:
                raise ValueError('ARMv7 requires a selected --inputs document with one board')
            bundles = kernels(args, document)
            components = {name: platform_inputs(args, name, document) for name in bundles}
            require_native_contract(args.orchard, components)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    omarchy = source_identity(PROJECT)
    component_records = {name: component_receipt(getattr(args, name + '_tools'))
                         for name in ('cursor', 'bluetooth', 'labwc')}
    base_record = json.loads(args.base_receipt.read_text())
    if not isinstance(base_record.get('release'), str) or not base_record['release']:
        parser.error('The base receipt must name its release stamp')
    if args.base_release is not None and base_record['release'] != args.base_release:
        parser.error('Base release differs from the expected cache stamp; rebuild the base component')
    cache_keys = {}
    if args.component_keys is not None:
        keys = json.loads(args.component_keys.read_text())
        cache_keys = keys.get('components', {})
        if (keys.get('schema') != 1 or keys.get('architecture') != args.architecture or
                set(cache_keys) != {'desktop', 'cursor', 'bluetooth', 'labwc', 'base', 'artwork'} or
                any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
                    for value in cache_keys.values())):
            parser.error('Invalid component cache-key receipt')
        if base_record['release'] != 'base-' + cache_keys['desktop'][:16]:
            parser.error('Base release stamp differs from its desktop cache key')
        if keys.get('producer') != producer:
            parser.error('Cached components name another Orchard build environment')
    initial_inputs = consumed_files(args, components, bundles)
    if any(initial_inputs.get(name) != receipt for name, receipt in initial_arguments.items()):
        raise ValueError('Consumed input changed before release assembly')
    root_tools = next(iter(components.values()), args)
    root = build_root(args.base, args.base_receipt, args.output, args.release,
                      args.cursor_tools, args.bluetooth_tools, args.labwc_tools,
                      tools={tool: getattr(root_tools, tool) for tool in ('dropbear', 'dropbearkey', 'busybox')},
                      splash=args.splash, architecture=args.architecture)
    public_root = dict(root)
    if public_root.get('stamps') != {'base': base_record['release'], 'orchard': args.release}:
        raise ValueError('Final root stamps differ from the base and release contract')
    if args.architecture == 'aarch64':
        offered = orchard_files(args)
        snapshot.command(args.orchard, 'orchard.image.root_image', args.output / 'rootfs.tar.zst', '--output', args.output)
        root = json.loads((args.output / 'root-image.json').read_text())
        shutil.copyfile(args.logo, args.output / 'logo.bin')
    else:
        platforms = {}
        for name, bundle in bundles.items():
            files = layer(components[name], name, bundle)
            boards = files.pop('boards')
            layer_architecture = files.pop('architecture', orchard_arch(args.architecture))
            if layer_architecture != orchard_arch(args.architecture):
                raise ValueError(f'{name}: platform layer architecture differs from root')
            image = recovery(components[name], name, bundle, snapshot.dtbs(args.orchard, boards), args.output / 'rootfs.json')
            platforms[name] = {'boards': boards, 'layer': files,
                               'boot': {'file': image.name, 'bytes': image.stat().st_size, 'sha256': sha(image)}}
        offered = platforms
    shutil.rmtree(args.output / '.work', ignore_errors=True)  # recovery and layer staging
    published = write_manifests(args.output, args.release, root, offered, revision, architecture=args.architecture)
    if source_identity(PROJECT) != omarchy:
        raise ValueError('Omarchy source changed during release assembly')
    if orchard_identity(args.orchard) != orchard_source:
        raise ValueError('Orchard source changed during release assembly')
    if consumed_files(args, components, bundles) != initial_inputs:
        raise ValueError('Consumed input changed during release assembly')
    for name, measured in component_records.items():
        if component_receipt(getattr(args, name + '_tools')) != measured:
            raise ValueError('Component changed during release assembly: ' + name)
    root_asset = args.output / 'rootfs.tar.zst'
    if file_receipt(root_asset) != {key: public_root[key] for key in ('bytes', 'sha256')}:
        raise ValueError('Final root archive differs from its receipt')
    # Assembly provenance is separate from the public installation contract.
    receipt = {'schema': 2, 'release': args.release, 'architecture': args.architecture,
               'orchard': revision, 'orchard_source': orchard_source, 'producer': producer,
               'omarchy': omarchy, 'components': component_records, 'cache_keys': cache_keys,
               'base': {'archive': file_receipt(args.base), 'receipt': file_receipt(args.base_receipt),
                        'metadata': base_record}, 'public_root': public_root, 'root': root,
               'platforms': offered['platforms'] if args.architecture == 'aarch64' else offered,
               'inputs': initial_inputs}
    (args.output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Release assets ready:', published)
    print('Pinned index:', args.output / 'index.toml')


if __name__ == '__main__':
    main()
