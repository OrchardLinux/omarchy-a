"""A release's native components must agree with its userspace ABI."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from release.architecture import check_elf, orchard_arch, platform_arch


PROJECT = Path(__file__).resolve().parents[1]
PRODUCER = {'orchard': {'commit': 'a' * 40, 'modified': False, 'tree_sha256': 'b' * 64},
            'buildenv': {'sha256': 'c' * 64}, 'wrapper': {'sha256': 'd' * 64}}


def executable(architecture):
    size, elf_class, machine = (64, 2, 183) if architecture == 'aarch64' else (52, 1, 40)
    data = bytearray(size)
    data[:7] = b'\x7fELF' + bytes((elf_class, 1, 1))
    struct.pack_into('<HHI', data, 16, 3, machine, 1)
    struct.pack_into('<H', data, 52 if elf_class == 2 else 40, size)
    if elf_class == 1:
        struct.pack_into('<I', data, 36, 0x05000400)
    return bytes(data)


def static_executable(architecture):
    arm = architecture == 'armv7h'
    data = bytearray(executable(architecture))
    offset, size = len(data), 32 if arm else 56
    data.extend(bytes(size))
    struct.pack_into('<I' if arm else '<Q', data, 28 if arm else 32, offset)
    struct.pack_into('<HH', data, 42 if arm else 54, size, 1)
    struct.pack_into('<I', data, offset, 1)
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
            platform(orchard, 'apple-16k', 'arm64')
            platform(orchard, 'apple-armv7', 'arm')
            calls, keys, inputs = [], {}, []
            tools = root / 'arm'
            tools.mkdir()
            for name in ('busybox', 'dropbear', 'dropbearkey'):
                (tools / name).write_bytes(static_executable('armv7h'))

            def component(project, name, inputs, produce, *, artifact, extra=()):
                target = root / 'components' / name / artifact
                produce(target, root / 'work')
                keys[name] = extra
                return target, 'f' * 64

            def command(module, *args):
                if module == 'orchard.inputs':
                    inputs.append(args)
                    path = Path(args[args.index('--output') + 1])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({'platforms': {'apple-armv7': {'boards': {'p105': 's5l8942x-p105'}}},
                                                'shared': {'tools': {name: str(tools / name) for name in
                                                                     ('busybox', 'dropbear', 'dropbearkey')}}}))

            argv = ['build', '--version', 'test', '--output', str(root / 'release'),
                    '--orchard', str(orchard), '--platform', 'apple-armv7']
            with patch.dict(os.environ, dict(os.environ)), patch.object(sys, 'argv', argv), patch.object(entry, 'PROJECT', root), \
                    patch.object(entry, 'component', component), patch.object(entry, 'orchard_command', command), \
                    patch.object(entry, 'builder_key', side_effect=lambda image: 'id:' + (image or '')), \
                    patch.object(entry, 'run', side_effect=lambda *args: calls.append(tuple(map(str, args)))):
                entry.main()
            self.assertEqual(inputs[0][-2:], ('--platform', 'apple-armv7'))
            for name in ('desktop', 'cursor', 'labwc', 'base'):
                self.assertIn('armv7h', keys[name])
                self.assertIn('id:' + entry.ARMV7_BUILDER, keys[name])
            for script in ('desktop/build', 'desktop/build-cursor-helper', 'desktop/build-labwc', 'system/build-rootfs'):
                call = next(call for call in calls if script in call)
                self.assertEqual(call[call.index('--architecture') + 1], 'armv7h')
                self.assertEqual(call[call.index('--builder-image') + 1], entry.ARMV7_BUILDER)
            release = next(call for call in calls if 'release.build' in call)
            self.assertEqual(release[release.index('--architecture') + 1], 'armv7h')
            self.assertEqual(release[release.index('--dropbear') + 1], str(tools / 'dropbear'))
            for removed in ('--device', '--loader', '--pongo', '--component-keys'):
                self.assertNotIn(removed, release)
            self.assertTrue(any('release.audit' in call for call in calls))

    def test_base_cache_invalidates_when_either_package_helper_changes(self):
        entry = build_entry()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in entry.INPUTS['base']:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT / name, target)
            produce = lambda path, work: path.write_text('base fixture')
            _, previous = entry.component(root, 'base', entry.INPUTS['base'], produce, artifact='base')
            for name in ('system/rank-mirrors', 'system/pacman-download'):
                path = root / name
                path.write_bytes(path.read_bytes() + b'\n# changed package helper\n')
                _, current = entry.component(root, 'base', entry.INPUTS['base'], produce, artifact='base')
                self.assertNotEqual(current, previous, name)
                previous = current

    def test_native_caches_bind_the_wrapper_and_selected_build_environment(self):
        entry = build_entry()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('desktop', 'cursor', 'labwc'):
                for relative in entry.INPUTS[name]:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('source fixture')
            make = lambda path, work: path.write_text('binary fixture')
            first = {}
            producer = json.dumps(PRODUCER, sort_keys=True)
            for name in ('desktop', 'cursor', 'labwc'):
                _, first[name] = entry.component(root, name, entry.INPUTS[name], make, artifact='binary', extra=[producer])
            (root / 'desktop/snapshot_buildenv.py').write_text('changed wrapper')
            second = {}
            for name in first:
                _, second[name] = entry.component(root, name, entry.INPUTS[name], make, artifact='binary', extra=[producer])
                self.assertNotEqual(first[name], second[name])
            changed = {**PRODUCER, 'buildenv': {'sha256': 'e' * 64}}
            for name in first:
                _, third = entry.component(root, name, entry.INPUTS[name], make, artifact='binary',
                                            extra=[json.dumps(changed, sort_keys=True)])
                self.assertNotEqual(second[name], third)


if __name__ == '__main__':
    unittest.main()
