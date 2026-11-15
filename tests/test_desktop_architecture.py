"""Architecture provenance is checked from executable bytes."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'desktop'))
from target import builder, source_pins


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

    def test_only_the_keyboard_is_compiled_from_a_pinned_source(self):
        self.assertEqual(set(source_pins()), {'wvkbd'})

    def test_receipt_verification_checks_the_keyboard_and_admits_no_package(self):
        desktop = load_desktop()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'desktop'
            payload = root / 'payload'
            payload.mkdir(parents=True)
            xpi = payload / desktop.XPI_PATH
            xpi.parent.mkdir(parents=True)
            xpi.write_bytes(b'extension fixture')
            keyboard = payload / desktop.KEYBOARD_PATH
            keyboard.parent.mkdir(parents=True)
            keyboard.write_bytes(elf('armv7h'))
            pin = source_pins()['wvkbd']
            contents = {name: desktop.sha(payload / name) for name in (desktop.XPI_PATH, desktop.KEYBOARD_PATH)}
            manifest = payload / 'arch-ipad-ui-manifest.json'
            manifest.write_text(json.dumps(contents))
            lock = dict(line.split('=', 1) for line in (PROJECT / 'desktop/upstream.lock').read_text().splitlines() if '=' in line)
            meta = {'architecture': 'armv7h', 'omarchy_commit': lock['omarchy_commit'],
                    'inputs': {'omafox_xpi': desktop.sha(xpi)},
                    'keyboard': desktop.keyboard_record('armv7h', pin['urls'][0], desktop.sha(keyboard)),
                    'payload_manifest_sha256': desktop.sha(manifest)}
            write = lambda: (root / 'manifest.json').write_text(json.dumps(meta))
            write()
            input_pins = Path(tmp) / 'inputs.json'
            input_pins.write_text(json.dumps({'architecture': 'aarch64', 'omafox_xpi': desktop.sha(xpi)}))
            with patch.object(desktop, 'PINS', input_pins):
                self.assertEqual(desktop.verify(root)['architecture'], 'armv7h')
                with self.assertRaisesRegex(ValueError, 'Desktop input manifest'):
                    desktop.verify(root, 'aarch64')
                # Packages come from the repositories: a desktop output carrying one is refused.
                (root / 'packages').mkdir()
                with self.assertRaisesRegex(ValueError, 'payload and nothing else'):
                    desktop.verify(root)
                (root / 'packages').rmdir()
                # A keyboard recipe other than this checkout's is refused.
                meta['keyboard']['recipe_sha256']['wvkbd-0.20.patch'] = '0' * 64
                write()
                with self.assertRaisesRegex(ValueError, 'Keyboard source or recipe'):
                    desktop.verify(root)
                meta['keyboard'] = desktop.keyboard_record('armv7h', pin['urls'][0], desktop.sha(keyboard))
                # A receipt with the selected architecture still cannot admit a foreign keyboard.
                keyboard.write_bytes(elf('aarch64'))
                meta['keyboard']['sha256'] = contents[desktop.KEYBOARD_PATH] = desktop.sha(keyboard)
                manifest.write_text(json.dumps(contents))
                meta['payload_manifest_sha256'] = desktop.sha(manifest)
                write()
                with self.assertRaisesRegex(ValueError, 'armv7h ELF'):
                    desktop.verify(root, 'armv7h')


if __name__ == '__main__':
    unittest.main()
