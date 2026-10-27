"""Publish per-device TOML manifests and their pinned index."""
import json
import os
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from orchard_hardware.image.integrity import sha
from release.devices import asset, device as device_spec

METHOD = 'checkm8-pongo'


def receipt(path):
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}


def write(output, version, root, device='j71b'):
    device_spec(device)
    document = ('schema = 1\nkind = "orchard.install"\ndistro = "omarchy-a"\n'
                'name = "Omarchy A"\nversion = ' + json.dumps(version) + '\n'
                'device = ' + json.dumps(device) + '\nboot_method = "' + METHOD + '"\n'
                'min_orchard = "0.1.5"\nprotocol = 1\n\n'
                '[install]\ndefault_root = "/omarchy"\n')
    for role, name in (('root', 'rootfs.tar.zst'), ('boot', 'recovery.bin'), ('pongo', 'pongo.bin')):
        item = receipt(output / asset(device, name))
        if role == 'root':
            item.update({key: root[key] for key in ('compression', 'expanded_bytes', 'members')})
        document += '\n[' + role + ']\n'
        document += ''.join(key + ' = ' + json.dumps(value) + '\n' for key, value in item.items())
    manifest = output / (device + '-' + METHOD + '.toml')
    with manifest.open('x') as stream:
        stream.write(document)
    write_index(output, [manifest])
    return manifest


def write_index(output, manifests, *, replace=False):
    """Pin sibling per-device manifests, one boot method each, sorted by device."""
    pins = {}
    for path in manifests:
        path = Path(path)
        value = tomllib.loads(path.read_text())
        profile = value.get('device')
        if (path.parent.resolve() != Path(output).resolve() or path.is_symlink() or
                value.get('kind') != 'orchard.install' or value.get('distro') != 'omarchy-a' or
                value.get('boot_method') != METHOD or path.name != str(profile) + '-' + METHOD + '.toml'):
            raise ValueError('Expected a sibling Omarchy installation manifest: ' + path.name)
        device_spec(profile)
        if profile in pins:
            raise ValueError('Duplicate device in release index: ' + profile)
        pins[profile] = receipt(path)
    if not pins:
        raise ValueError('A release index needs at least one device')
    index = 'schema = 1\nkind = "orchard.index"\ndistro = "omarchy-a"\n'
    for profile in sorted(pins):
        index += '\n[devices.' + profile + '.' + METHOD + ']\n'
        index += ''.join(key + ' = ' + json.dumps(value) + '\n' for key, value in pins[profile].items())
    path = Path(output) / 'index.toml'
    if not replace:
        with path.open('x') as stream:
            stream.write(index)
        return path
    pending = path.with_name('.index.toml.pending')
    with pending.open('x') as stream:
        stream.write(index)
    os.replace(pending, path)
    return path


def read_release(manifest):
    """Read installation metadata for artifact audits and smoke tests."""
    value = tomllib.loads(Path(manifest).read_text())
    if value.get('schema') != 1 or value.get('kind') != 'orchard.install' or value.get('distro') != 'omarchy-a':
        raise ValueError('Expected an Omarchy Orchard installation manifest')
    return {'schema': value['schema'], 'protocol': value['protocol'],
            'profile': value['device'], 'release': value['version'],
            'assets': {role: value[key] for role, key in (
                ('root', 'root'), ('recovery', 'boot'), ('pongo', 'pongo'))}}
