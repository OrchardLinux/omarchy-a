"""Architecture provenance is checked from package and executable bytes."""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tarfile
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'desktop'))
from target import builder, check_package, source_pins


def elf(architecture):
    data = bytearray(64)
    data[:7] = b'\x7fELF' + bytes((1 if architecture == 'armv7h' else 2, 1, 1))
    struct.pack_into('<HHI', data, 16, 3, 40 if architecture == 'armv7h' else 183, 1)
    struct.pack_into('<H', data, 40 if architecture == 'armv7h' else 52, 52 if architecture == 'armv7h' else 64)
    if architecture == 'armv7h':
        struct.pack_into('<I', data, 36, 0x05000400)
    return bytes(data)


def load_desktop():
    source = PROJECT / 'desktop/build'
    loader = importlib.machinery.SourceFileLoader('omarchy_desktop_build', str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'snapshot_buildenv': SimpleNamespace(buildenv=FakeBuildenv())}):
        loader.exec_module(module)
    return module


def package(path, architecture, executable=None):
    with tarfile.open(path, 'w:xz') as archive:
        data = ('pkgname = fixture\narch = ' + architecture + '\n').encode()
        item = tarfile.TarInfo('.PKGINFO')
        item.size = len(data)
        archive.addfile(item, io.BytesIO(data))
        if executable is not None:
            item = tarfile.TarInfo('usr/bin/fixture')
            item.size = len(executable)
            archive.addfile(item, io.BytesIO(executable))


class FakeBuildenv:
    def __init__(self, native=False):
        self.is_native = native
        self.calls = []

    def native(self):
        return self.is_native

    def build(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class DesktopArchitecture(unittest.TestCase):
    def test_native_builder_rejects_wrong_machine(self):
        with patch('target.platform.machine', return_value='aarch64'):
            with self.assertRaisesRegex(ValueError, 'architecture differs'):
                builder(FakeBuildenv(True), 'armv7h')

    def test_armv7_container_requires_an_explicit_target_builder(self):
        environment = FakeBuildenv()
        with self.assertRaisesRegex(ValueError, '--builder-image'):
            builder(environment, 'armv7h')
        self.assertEqual(environment.calls, [])
        self.assertEqual(builder(environment, 'armv7h', 'compiler:armv7'), 'compiler:armv7')
        self.assertEqual(environment.calls, [])

    def test_default_aarch64_builder_keeps_pinned_recipe(self):
        environment = FakeBuildenv()
        self.assertEqual(builder(environment, 'aarch64'), 'localhost/omarchy-a-desktop-builder:arm64')
        self.assertEqual(environment.calls[0][1], {'arch': 'arm64'})
        self.assertEqual(environment.calls[0][0][1], PROJECT / 'desktop/Containerfile')

    @unittest.skipUnless(shutil.which('bsdtar'), 'package verification uses libarchive')
    def test_package_header_cannot_be_relabelled_by_a_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'component.pkg.tar.xz'
            package(path, 'aarch64')
            with self.assertRaisesRegex(ValueError, 'architecture differs'):
                check_package(path, 'armv7h')
            self.assertEqual(check_package(path, 'aarch64'), 'aarch64')
            package(path, 'armv7h')
            self.assertEqual(check_package(path, 'armv7h'), 'armv7h')
            package(path, 'armv7h', elf('aarch64'))
            with self.assertRaisesRegex(ValueError, 'armv7h ELF'):
                check_package(path, 'armv7h')
            package(path, 'armv7h', elf('armv7h'))
            self.assertEqual(check_package(path, 'armv7h'), 'armv7h')

    def test_armv7_source_set_includes_pinned_omacalc(self):
        pins = source_pins('armv7h')
        self.assertEqual(pins['omacalc']['commit'], '573d7106f5c6c0225864eb8634ae37ddcb657f63')
        self.assertEqual(pins['omacalc']['sha256'], '6a4ad731acb4f68226b975e1b817b2907fea1534d52d1e769564a76a48f3eafc')
        self.assertNotIn('omacalc', source_pins('aarch64'))

    @unittest.skipUnless(shutil.which('bsdtar'), 'package verification uses libarchive')
    def test_receipt_verification_checks_target_packages_and_keyboard(self):
        desktop = load_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, packages = root / 'payload', root / 'packages'
            payload.mkdir(); packages.mkdir()
            xpi = payload / desktop.XPI_PATH
            xpi.parent.mkdir(parents=True)
            xpi.write_bytes(b'extension fixture')
            keyboard = payload / desktop.KEYBOARD_PATH
            keyboard.parent.mkdir(parents=True)
            keyboard.write_bytes(elf('armv7h'))
            for name in ('omafox.pkg.tar.xz', 'wlroots0.20.pkg.tar.xz', 'omacalc.pkg.tar.zst'):
                package(packages / name, 'armv7h')
            pins = source_pins('armv7h')
            files = {name: desktop.sha(packages / name) for name in ('omafox.pkg.tar.xz', 'wlroots0.20.pkg.tar.xz', 'omacalc.pkg.tar.zst')}
            files['wvkbd-mobintl'] = desktop.sha(keyboard)
            built = {'architecture': 'armv7h', 'source_sha256': {name: value['sha256'] for name, value in pins.items()},
                     'source_urls': {name: value['urls'][0] for name, value in pins.items()},
                     'patch_sha256': desktop.sha(PROJECT / 'desktop/keyboard/wvkbd-0.20.patch'),
                     'pkgbuild_sha256': desktop.sha(PROJECT / 'desktop/packages/omafox/PKGBUILD'),
                     'wlroots_recipe_sha256': desktop.recipe_sha(PROJECT / 'desktop/packages/wlroots0.20'),
                     'omacalc_recipe_sha256': desktop.recipe_sha(PROJECT / 'desktop/packages/omacalc'), 'files': files}
            contents = {name: desktop.sha(payload / name) for name in (desktop.XPI_PATH, desktop.KEYBOARD_PATH)}
            manifest = payload / 'arch-ipad-ui-manifest.json'
            manifest.write_text(json.dumps(contents))
            lock = dict(line.split('=', 1) for line in (PROJECT / 'desktop/upstream.lock').read_text().splitlines() if '=' in line)
            meta = {'architecture': 'armv7h', 'omarchy_commit': lock['omarchy_commit'],
                    'inputs': {'omafox_xpi': desktop.sha(xpi)}, 'source_build': built,
                    'payload_manifest_sha256': desktop.sha(manifest)}
            (root / 'manifest.json').write_text(json.dumps(meta))
            input_pins = root / 'inputs.json'
            input_pins.write_text(json.dumps({'architecture': 'aarch64', 'omafox_xpi': desktop.sha(xpi)}))
            with patch.object(desktop, 'PINS', input_pins):
                self.assertEqual(desktop.verify(root)['architecture'], 'armv7h')
                with self.assertRaisesRegex(ValueError, 'Desktop input manifest'):
                    desktop.verify(root, 'aarch64')
                # A receipt with the selected architecture still cannot admit a foreign package.
                package(packages / 'omafox.pkg.tar.xz', 'aarch64')
                built['files']['omafox.pkg.tar.xz'] = desktop.sha(packages / 'omafox.pkg.tar.xz')
                (root / 'manifest.json').write_text(json.dumps(meta))
                with self.assertRaisesRegex(ValueError, 'Package architecture'):
                    desktop.verify(root, 'armv7h')
                package(packages / 'omafox.pkg.tar.xz', 'armv7h')
                built['files']['omafox.pkg.tar.xz'] = desktop.sha(packages / 'omafox.pkg.tar.xz')
                keyboard.write_bytes(elf('aarch64'))
                built['files']['wvkbd-mobintl'] = desktop.sha(keyboard)
                contents[desktop.KEYBOARD_PATH] = desktop.sha(keyboard)
                manifest.write_text(json.dumps(contents))
                meta['payload_manifest_sha256'] = desktop.sha(manifest)
                (root / 'manifest.json').write_text(json.dumps(meta))
                with self.assertRaisesRegex(ValueError, 'armv7h ELF'):
                    desktop.verify(root, 'armv7h')


if __name__ == '__main__':
    unittest.main()
