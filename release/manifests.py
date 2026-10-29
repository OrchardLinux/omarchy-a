"""Publish a single-target TOML manifest and its pinned index."""
import json
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib

from orchard_hardware.image.integrity import sha


def receipt(path):
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}


def write(output, version, root):
    document = ('schema = 1\nkind = "orchard.install"\ndistro = "omarchy-a"\n'
                'name = "Omarchy A"\nversion = ' + json.dumps(version) + '\n'
                'device = "j71b"\nboot_method = "checkm8-pongo"\n'
                'min_orchard = "0.1.11"\nprotocol = 1\n\n'
                '[install]\ndefault_root = "/omarchy"\n')
    for role, name in (('root', 'rootfs.tar.zst'), ('boot', 'recovery.bin'), ('pongo', 'pongo.bin')):
        item = receipt(output / name)
        if role == 'root':
            item.update({key: root[key] for key in ('compression', 'expanded_bytes', 'members')})
        document += '\n[' + role + ']\n'
        document += ''.join(key + ' = ' + json.dumps(value) + '\n' for key, value in item.items())
    manifest = output / 'j71b-checkm8-pongo.toml'
    with manifest.open('x') as stream:
        stream.write(document)
    pin = receipt(manifest)
    index = 'schema = 1\nkind = "orchard.index"\ndistro = "omarchy-a"\n\n[devices.j71b.checkm8-pongo]\n'
    index += ''.join(key + ' = ' + json.dumps(value) + '\n' for key, value in pin.items())
    with (output / 'index.toml').open('x') as stream:
        stream.write(index)
    return manifest


def read_release(manifest):
    """Read installation metadata for artifact audits and smoke tests."""
    value = tomllib.loads(Path(manifest).read_text())
    if value.get('schema') != 1 or value.get('kind') != 'orchard.install' or value.get('distro') != 'omarchy-a':
        raise ValueError('Expected an Omarchy Orchard installation manifest')
    return {'schema': value['schema'], 'protocol': value['protocol'],
            'profile': value['device'], 'release': value['version'],
            'assets': {role: value[key] for role, key in (
                ('root', 'root'), ('recovery', 'boot'), ('pongo', 'pongo'))}}
