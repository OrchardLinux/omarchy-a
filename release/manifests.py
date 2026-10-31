"""Publish the release's install manifest (every platform) and the index that pins it."""
import json
from pathlib import Path
import tomllib

from orchard.image.integrity import sha


def receipt(path):
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}


def table(name, row):
    return '\n[' + name + ']\n' + ''.join(key + ' = ' + json.dumps(value) + '\n' for key, value in row.items())


def write(output, version, root, platforms, orchard):
    """release.toml and index.toml in OUTPUT.

    PLATFORMS maps each platform to its boards, recovery (`boot`) and
    orchard layer receipts; ORCHARD is orchard.hardware.revision().
    """
    document = ('schema = 2\nkind = "orchard.install"\ndistro = "omarchy-a"\n'
                'name = "Omarchy A"\nversion = ' + json.dumps(version) + '\n'
                'boot_method = "checkm8-pongo"\nmin_orchard = "0.2.0"\nprotocol = 1\n')
    document += table('orchard', orchard)
    # The tablet user gets the password and the lock-screen PIN at install. The
    # installer waits over this boot's SSH for the desktop's ready record.
    document += table('install', {'default_root': '/omarchy',
                                  'ready': '/run/user/1000/omarchy-desktop-ready.json'})
    document += table('install.account', {'user': 'tablet', 'password': True, 'pin': True,
                                          'passwordless_sudo': False})
    row = receipt(output / 'rootfs.tar.zst')
    row.update({key: root[key] for key in ('compression', 'expanded_bytes', 'members')})
    document += table('root', row)
    document += table('pongo', receipt(output / 'pongo.bin'))
    for name, files in sorted(platforms.items()):
        document += f'\n[platforms.{name}]\nboards = {json.dumps(files["boards"])}\n'
        document += table(f'platforms.{name}.boot', files['boot'])
        document += table(f'platforms.{name}.layer', files['layer'])
    manifest = output / 'release.toml'
    with manifest.open('x') as stream:
        stream.write(document)
    index = 'schema = 2\nkind = "orchard.index"\ndistro = "omarchy-a"\n' + table('release', receipt(manifest))
    with (output / 'index.toml').open('x') as stream:
        stream.write(index)
    return manifest


def read_release(manifest):
    """Read installation metadata for artifact audits and smoke tests."""
    value = tomllib.loads(Path(manifest).read_text())
    if value.get('schema') != 2 or value.get('kind') != 'orchard.install' or value.get('distro') != 'omarchy-a':
        raise ValueError('Expected an Omarchy Orchard installation manifest')
    return {'schema': value['schema'], 'protocol': value['protocol'], 'release': value['version'],
            'root': value['root'], 'pongo': value['pongo'], 'platforms': value['platforms']}
