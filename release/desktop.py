"""Receipt-checked desktop components shared by AArch64 images."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe desktop component path")
    return str(path)


def cursor_files(directory, project):
    record = json.loads((directory / 'manifest.json').read_text())
    pin = json.loads((project / 'desktop/cursor/wtype.json').read_text())
    if record.get('schema') != 1 or record.get('architecture') != 'aarch64' or record.get('source') != pin:
        raise ValueError('Incompatible startup cursor helper receipt')
    files = {}
    for name, destination, mode in (
            ('wtype', 'usr/libexec/omarchy-wtype', 0o755),
            ('LICENSE', 'usr/share/licenses/omarchy-wtype/LICENSE', 0o644)):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Invalid startup cursor helper file: ' + name)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record['files'].get(name):
            raise ValueError('Startup cursor helper differs from receipt: ' + name)
        files[destination] = (data, mode)
    files['etc/omarchy/cursor-helper.json'] = (json.dumps(record, sort_keys=True).encode(), 0o644)
    return files


def bluetooth_files(directory, project):
    record = json.loads((directory / 'manifest.json').read_text())
    pin = json.loads((project / 'desktop/bluetooth/dbus-next.json').read_text())
    if record.get('schema') != 1 or record.get('source') != pin:
        raise ValueError('Incompatible Bluetooth dependency receipt')
    files = {}
    if not {'lib/dbus_next/__init__.py', 'LICENSE'} <= record['files'].keys():
        raise ValueError('Incomplete Bluetooth dependency receipt')
    for name, digest in record['files'].items():
        if name != 'LICENSE' and not (name.startswith('lib/dbus_next/') and name.endswith('.py')):
            raise ValueError('Unexpected Bluetooth dependency file')
        if safe_name(name) != name:
            raise ValueError('Unsafe Bluetooth dependency path')
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Invalid Bluetooth dependency file')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Bluetooth dependency differs from receipt')
        destination = ('usr/share/licenses/omarchy-bluetooth-dbus-next/LICENSE' if name == 'LICENSE'
                       else 'usr/lib/omarchy-bluetooth/' + name.removeprefix('lib/'))
        files[destination] = (data, 0o644)
    files['etc/omarchy/bluetooth-helper.json'] = (json.dumps(record, sort_keys=True).encode(), 0o644)
    return files


def labwc_files(directory, project):
    record = json.loads((directory / 'manifest.json').read_text())
    pin = json.loads((project / 'desktop/labwc/source.json').read_text())
    if record.get('schema') != 1 or record.get('source') != pin:
        raise ValueError('Incompatible Labwc component receipt')
    expected = {'labwc', 'LICENSE', 'source.tar.gz', '0001-cancel-super-tap-on-pointer.patch',
                'packages.lock', 'compiler.txt', 'version.txt'}
    if record.get('files', {}).keys() != expected:
        raise ValueError('Incomplete Labwc component')
    files = {}
    for name, digest in record['files'].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise ValueError('Labwc component differs from receipt')
        destination = 'usr/bin/labwc' if name == 'labwc' else 'usr/share/licenses/omarchy-labwc/' + name
        files[destination] = (path.read_bytes(), 0o755 if name == 'labwc' else 0o644)
    if record['files']['source.tar.gz'] != pin['sha256'] or record['files']['0001-cancel-super-tap-on-pointer.patch'] != pin['patch_sha256']:
        raise ValueError('Labwc corresponding source differs from pin')
    files['etc/omarchy/labwc-helper.json'] = (json.dumps(record, sort_keys=True).encode(), 0o644)
    return files
