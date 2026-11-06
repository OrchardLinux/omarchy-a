"""Publish the release's install manifest (every platform) and the index that pins it."""
import hashlib
import json
from pathlib import Path
import tomllib

from release.architecture import validate, platform_arch


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

    PLATFORMS maps each platform to its boards, recovery (`boot`) and
    orchard layer receipts; ORCHARD is the snapshot's revision ({'commit', 'modified'}).
    """
    validate(architecture)
    platforms = offered['platforms'] if architecture == 'aarch64' else offered
    if root.get('architecture', 'aarch64') != architecture:
        raise ValueError('Root receipt architecture differs from release')
    if any(platform_arch(name) != architecture for name in platforms):
        raise ValueError('Release platforms do not share the root architecture')
    boot_method = 'recovery-autogo' if architecture == 'armv7h' else 'checkm8-pongo'
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
    if architecture == 'aarch64':
        document += table('root', {key: value for key, value in root.items() if key != 'map'})
        document += table('root.map', root['map'])
        document += table('logo', receipt(output / 'logo.bin'))
        document += table('pongo', offered['loaders']['pongo'])
        document += table('m1n1', offered['loaders']['m1n1'])
        document += table('install_tools', offered['install_tools'])
        for name, layer in sorted(platforms.items()):
            document += f'\n[platforms.{name}]\nboards = {json.dumps(layer["boards"])}\n'
            document += table(f'platforms.{name}.layer', {key: value for key, value in layer.items() if key != 'boards'})
    else:
        row = receipt(output / 'rootfs.tar.zst')
        row.update({key: root[key] for key in ('compression', 'expanded_bytes', 'members')})
        document += table('root', row)
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
    architectures = {platform_arch(name) for name in value['platforms']}
    if len(architectures) != 1:
        raise ValueError('Release platforms do not share one userspace architecture')
    architecture = architectures.pop()
    expected_method = 'recovery-autogo' if architecture == 'armv7h' else 'checkm8-pongo'
    if value.get('boot_method') != expected_method:
        raise ValueError('Release boot method differs from its platform architecture')
    return {'schema': value['schema'], 'protocol': value['protocol'], 'release': value['version'],
            'architecture': architecture, 'boot_method': value['boot_method'],
            'root': value['root'], 'pongo': value.get('pongo'), 'm1n1': value.get('m1n1'),
            'install_tools': value.get('install_tools'), 'logo': value.get('logo'), 'platforms': value['platforms']}
