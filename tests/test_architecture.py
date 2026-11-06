"""A release's native components must agree with its userspace ABI."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from release.architecture import check_elf, orchard_arch, platform_arch


PROJECT = Path(__file__).resolve().parents[1]


def executable(architecture):
    size, elf_class, machine = (64, 2, 183) if architecture == 'aarch64' else (52, 1, 40)
    data = bytearray(size)
    data[:7] = b'\x7fELF' + bytes((elf_class, 1, 1))
    struct.pack_into('<HHI', data, 16, 3, machine, 1)
    struct.pack_into('<H', data, 52 if elf_class == 2 else 40, size)
    if elf_class == 1:
        struct.pack_into('<I', data, 36, 0x05000400)
    return bytes(data)


def build_entry():
    spec = importlib.util.spec_from_file_location('architecture_build', PROJECT / 'tools/build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def platform(snapshot, name, arch):
    path = snapshot / 'platforms' / (name + '.toml')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[kernel]\narch = ' + json.dumps(arch) + '\n')


class ExecutableArchitectureTests(unittest.TestCase):
    def test_accepted_targets_have_distinct_elf_classes_and_machines(self):
        for architecture in ('aarch64', 'armv7h'):
            with self.subTest(architecture=architecture):
                self.assertEqual(check_elf(executable(architecture), architecture), architecture)
                other = 'armv7h' if architecture == 'aarch64' else 'aarch64'
                with self.assertRaisesRegex(ValueError, 'ELF'):
                    check_elf(executable(other), architecture)

    def test_arm_soft_float_and_old_eabi_are_rejected(self):
        for flags in (0x05000200, 0x05000000, 0x05000600, 0x04000400):
            data = bytearray(executable('armv7h'))
            struct.pack_into('<I', data, 36, flags)
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, 'hard-float'):
                check_elf(data, 'armv7h')

    def test_bad_framing_and_non_executables_are_rejected(self):
        for offset, value in ((5, 2), (6, 0), (16, 1), (18, 62), (20, 2), (40, 51)):
            data = bytearray(executable('armv7h'))
            data[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                check_elf(data, 'armv7h')
        with self.assertRaises(ValueError):
            check_elf(executable('armv7h')[:51], 'armv7h')

    def test_path_check_reads_header_from_actual_component(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'helper'
            path.write_bytes(executable('armv7h') + bytes(4096))
            self.assertEqual(check_elf(path, 'armv7h'), 'armv7h')


class ArchitectureSelectionTests(unittest.TestCase):
    def test_platform_descriptor_selects_userspace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            platform(root, 'future-arm-board', 'arm')
            self.assertEqual(platform_arch('future-arm-board', root), 'armv7h')
            self.assertEqual(orchard_arch('armv7h'), 'arm')
            with self.assertRaises(ValueError):
                platform_arch('../future-arm-board', root)

    def test_default_keeps_arm64_platforms_and_explicit_armv7_infers_abi(self):
        entry = build_entry()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            platform(root, 'apple-16k', 'arm64')
            platform(root, 'apple-4k', 'arm64')
            platform(root, 'apple-armv7', 'arm')
            self.assertEqual(entry.targets(root, []), ('aarch64', ['apple-16k', 'apple-4k']))
            self.assertEqual(entry.targets(root, ['apple-armv7']), ('armv7h', ['apple-armv7']))
            self.assertEqual(entry.targets(root, ['all'], 'armv7h'), ('armv7h', ['apple-armv7']))
            for names, arch in ((['apple-16k', 'apple-armv7'], None), (['apple-armv7'], 'aarch64'),
                                (['all', 'apple-armv7'], None)):
                with self.subTest(names=names, arch=arch), self.assertRaises(ValueError):
                    entry.targets(root, names, arch)

    def test_build_propagates_isa_and_separates_component_cache_keys(self):
        entry = build_entry()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            orchard = root / 'orchard'
            (orchard / 'src/orchard').mkdir(parents=True)
            platform(orchard, 'apple-armv7', 'arm')
            device = orchard / 'devices/p105/device.toml'
            device.parent.mkdir(parents=True)
            device.write_text('[kernel]\nplatform = "apple-armv7"\n')
            calls, keys = [], {}
            tools = root / 'arm'
            tools.mkdir()
            for name in ('cascadia.bin', *entry.TOOLS):
                (tools / name).write_bytes(b'component')

            def component(project, name, inputs, produce, *, artifact, extra=()):
                target = root / 'components' / name / artifact
                produce(target, root / 'work')
                keys[name] = extra
                return target, 'f' * 64

            def command(module, *args):
                if module == 'orchard.inputs':
                    self.assertEqual(args[args.index('--device') + 1], 'p105')
                    path = Path(args[args.index('--output') + 1])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({'platforms': {'apple-armv7': {
                        'tools': {name: str(tools / name) for name in
                                  ('busybox', 'dropbear', 'dropbearkey', 'wpa_supplicant', 'wpa_cli', 'iw')},
                        'loader': {'kind': 'cascadia', 'file': str(tools / 'cascadia.bin')}}}}))

            argv = ['build', '--version', 'test', '--output', str(root / 'release'),
                    '--orchard', str(orchard), '--device', 'p105']
            with patch.dict(os.environ, dict(os.environ)), patch.object(sys, 'argv', argv), patch.object(entry, 'PROJECT', root), \
                    patch.object(entry, 'component', component), patch.object(entry, 'orchard_command', command), \
                    patch.object(entry, 'run', side_effect=lambda *args: calls.append(tuple(map(str, args)))):
                entry.main()
            for name in ('desktop', 'cursor', 'labwc', 'base'):
                self.assertIn('armv7h', keys[name])
            for script in ('desktop/build', 'desktop/build-cursor-helper', 'desktop/build-labwc', 'system/build-rootfs'):
                call = next(call for call in calls if script in call)
                self.assertEqual(call[call.index('--architecture') + 1], 'armv7h')
            release = next(call for call in calls if 'release.build' in call)
            self.assertEqual(release[release.index('--loader') + 1], str(tools / 'cascadia.bin'))
            self.assertNotIn('--pongo', release)

    def test_missing_lwvm_input_stops_before_root_or_component_build(self):
        entry = build_entry()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            orchard = root / 'orchard'
            (orchard / 'src/orchard').mkdir(parents=True)
            platform(orchard, 'apple-armv7', 'arm')
            tools = root / 'arm'
            tools.mkdir()
            for name in ('cascadia.bin', *entry.TOOLS):
                (tools / name).write_bytes(b'component')

            def command(module, *args):
                self.assertEqual(module, 'orchard.inputs')
                path = Path(args[args.index('--output') + 1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'platforms': {'apple-armv7': {
                    'root_format': 'lwvm', 'boards': {'p105': 's5l8942x-p105'},
                    'tools': {name: str(tools / name) for name in entry.TOOLS},
                    'loader': {'kind': 'cascadia', 'file': str(tools / 'cascadia.bin')}}}}))

            argv = ['build', '--version', 'test', '--output', str(root / 'release'),
                    '--orchard', str(orchard), '--platform', 'apple-armv7']
            with patch.dict(os.environ, dict(os.environ)), patch.object(sys, 'argv', argv), \
                    patch.object(entry, 'PROJECT', root), patch.object(entry, 'orchard_command', command), \
                    patch.object(entry, 'component') as component, \
                    self.assertRaisesRegex(ValueError, 'requires tools.lwvm'):
                entry.main()
            component.assert_not_called()


if __name__ == '__main__':
    unittest.main()
