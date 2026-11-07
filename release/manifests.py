"""Publish the release's install manifest (every platform of its architecture) and the index that pins it."""
import hashlib
import json
from pathlib import Path
import tomllib

from release.architecture import validate

# Per root architecture: the index orchard.image.platforms_index writes (arm64: platforms.toml; the 32-bit
# platforms have their own), and how the release's boards start when the index doesn't say.
INDEXES = {'aarch64': 'platforms.toml', 'armv7h': 'platforms-armv7.toml'}
BOOT_METHODS = {'aarch64': 'checkm8-pongo', 'armv7h': 'cascadia'}
# Tables of the manifest that are not one of orchard's loaders.
NOT_LOADERS = ('orchard', 'install', 'root', 'logo', 'install_tools', 'platforms')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def receipt(path):
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}


def table(name, row):
    return '\n[' + name + ']\n' + ''.join(key + ' = ' + json.dumps(value) + '\n' for key, value in row.items())


def write(output, version, root, offered, orchard, *, architecture='aarch64'):
    """release.toml and index.toml in OUTPUT.

    ROOT is orchard.image.root_image's table, OFFERED orchard's index of the root's architecture
    beside it (platforms.toml, or the 32-bit index); ORCHARD is the snapshot's revision
    ({'commit', 'modified'}).
    """
    validate(architecture)
    boot_method = offered.get('boot_method', BOOT_METHODS[architecture])
    document = ('schema = 2\nkind = "orchard.install"\ndistro = "omarchy-a"\n'
                'name = "Omarchy A"\nversion = ' + json.dumps(version) + '\n'
                'boot_method = ' + json.dumps(boot_method) + '\nmin_orchard = "0.2.0"\nprotocol = 1\n')
    document += table('orchard', orchard)
    # The tablet user gets the password and the lock-screen PIN at install. The
    # installer waits over this boot's SSH for the greeter's ready record: the
    # PIN screen is on.
    document += table('install', {'default_root': '/omarchy',
                                  'ready': '/run/omarchy-greeter/ready.json'})
    document += table('install.account', {'user': 'tablet', 'password': True, 'pin': True,
                                          'passwordless_sudo': False})
    document += table('root', {key: value for key, value in root.items() if key != 'map'})
    document += table('root.map', root['map'])
    document += table('logo', receipt(output / 'logo.bin'))
    # orchard's loaders as its index names them (arm64: pongo and m1n1).
    for name, row in offered['loaders'].items():
        document += table(name, row)
    document += table('install_tools', offered['install_tools'])
    for name, layer in sorted(offered['platforms'].items()):
        document += f'\n[platforms.{name}]\nboards = {json.dumps(layer["boards"])}\n'
        document += table(f'platforms.{name}.layer', {key: value for key, value in layer.items() if key != 'boards'})
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
    loaders = {key: row for key, row in value.items() if isinstance(row, dict) and key not in NOT_LOADERS}
    return {'schema': value['schema'], 'protocol': value['protocol'], 'release': value['version'],
            'boot_method': value['boot_method'], 'root': value['root'], 'loaders': loaders,
            'pongo': value.get('pongo'), 'm1n1': value.get('m1n1'),
            'install_tools': value['install_tools'], 'logo': value['logo'], 'platforms': value['platforms']}
