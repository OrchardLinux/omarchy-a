"""Publish the release's install manifest (every platform of its architecture) and the index that pins it."""
import hashlib
import json
from pathlib import Path
import tomllib

from release.architecture import validate

# Per root architecture: the index orchard.image.platforms_index writes (arm64: platforms.toml; the 32-bit
# platforms have their own), and how the release's boards start when the index doesn't say.
# Per root architecture: orchard's name for it, its index and the manifest's boot method
# (orchard docs/distribution-contract.md, "32-bit roots").
INDEXES = {'aarch64': 'platforms.toml', 'armv7h': 'platforms-armv7.toml'}
ORCHARD_ARCHITECTURES = {'aarch64': 'arm64', 'armv7h': 'arm'}
BOOT_METHODS = {'aarch64': 'checkm8-pongo', 'armv7h': 'recovery-autogo'}


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
    boot_method = BOOT_METHODS[architecture]
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
    if architecture == 'aarch64':
        document += table('logo', receipt(output / 'logo.bin'))
        document += table('pongo', offered['loaders']['pongo'])
        document += table('m1n1', offered['loaders']['m1n1'])
    else:
        # A 32-bit release names each board's Cascadia loader; it has no Pongo, m1n1 or logo.
        for board, row in sorted(offered['loaders']['cascadia'].items()):
            document += table(f'cascadia.{board}', row)
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
    # The files that start the release: Pongo and m1n1, or each board's Cascadia loader.
    loaders = ({f'cascadia {board}': row for board, row in value['cascadia'].items()} if 'cascadia' in value else
               {name: value[name] for name in ('pongo', 'm1n1') if name in value})
    return {'schema': value['schema'], 'protocol': value['protocol'], 'release': value['version'],
            'boot_method': value['boot_method'], 'root': value['root'], 'loaders': loaders,
            'pongo': value.get('pongo'), 'm1n1': value.get('m1n1'),
            'install_tools': value['install_tools'], 'logo': value.get('logo'), 'platforms': value['platforms']}
