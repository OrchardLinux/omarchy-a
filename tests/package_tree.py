"""The omarchy-a package's files as `make install` lays them out (desktop/install-tree), with stand-ins
for the compiled helpers and the fetched sources: what tests read instead of the recipe's build."""
import functools
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

# Tests run helpers out of the shared tree; they must not leave __pycache__ in it.
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

PROJECT = Path(__file__).resolve().parents[1]
INSTALL = PROJECT / 'desktop/install-tree'


def elf(architecture='aarch64'):
    arm = architecture == 'armv7h'
    data = bytearray(52 if arm else 64)
    data[:7] = b'\x7fELF' + bytes((1 if arm else 2, 1, 1))
    struct.pack_into('<HHI', data, 16, 3, 40 if arm else 183, 1)
    struct.pack_into('<H', data, 40 if arm else 52, len(data))
    if arm:
        struct.pack_into('<I', data, 36, 0x05000400)
    return bytes(data)


def inputs(base):
    """BUILD, OMARCHY and DBUS_NEXT for install-tree, under BASE."""
    build, upstream, wheel = base / 'build', base / 'omarchy', base / 'wheel'
    build.mkdir()
    for name in ('wvkbd-mobintl', 'wtype'):
        (build / name).write_bytes(elf())
    (build / 'wtype.LICENSE').write_text('MIT\n')
    (upstream / 'themes/jade-horse/backgrounds').mkdir(parents=True)
    (upstream / 'themes/jade-horse/backgrounds/01-mountain-horses.webp').write_bytes(b'RIFF\0\0\0\0WEBP')
    (upstream / 'themes/jade-horse/colors.toml').write_text('foreground = "#d4e0d0"\n')
    (upstream / 'themes/tokyo-night').mkdir(parents=True)
    (upstream / 'themes/tokyo-night/colors.toml').write_text('foreground = "#c0caf5"\n')
    outside = base / 'outside-theme'
    outside.mkdir(mode=0o711)
    outside.chmod(0o711)
    (upstream / 'themes/external-theme').symlink_to(outside, target_is_directory=True)
    (upstream / 'applications').mkdir()
    (upstream / 'applications/foot.desktop').write_text('[Desktop Entry]\nName=Terminal\n')
    (wheel / 'dbus_next/aio').mkdir(parents=True)
    (wheel / 'dbus_next/__init__.py').write_text('# dbus\n')
    (wheel / 'dbus_next/aio/__init__.py').write_text('# aio\n')
    (wheel / 'dbus_next-0.2.3.dist-info').mkdir()
    (wheel / 'dbus_next-0.2.3.dist-info/LICENSE').write_text('MIT\n')
    return build, upstream, wheel


def install(root, base, umask=0o077):
    build, upstream, wheel = inputs(base)
    previous = os.umask(umask)
    try:
        return subprocess.run(['bash', str(INSTALL), str(root), str(build), str(upstream), str(wheel)],
                              capture_output=True, text=True, timeout=120)
    finally:
        os.umask(previous)


@functools.lru_cache(maxsize=None)
def tree():
    """One installed tree for every test that only reads it."""
    base = Path(tempfile.mkdtemp(prefix='omarchy-a-tree-'))
    result = install(base / 'root', base)
    if result.returncode:
        raise AssertionError('desktop/install-tree failed:\n' + result.stderr + result.stdout)
    import atexit
    atexit.register(shutil.rmtree, base, True)
    return base / 'root'


def mode(path):
    return path.stat().st_mode & 0o777


def system_files():
    """{path in the package: (bytes, mode)} of every file the package installs."""
    root = tree()
    return {path.relative_to(root).as_posix(): (path.read_bytes(), mode(path))
            for path in root.rglob('*') if path.is_file() and not path.is_symlink()}
