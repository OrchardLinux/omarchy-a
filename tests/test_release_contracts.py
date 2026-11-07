"""ARM64 consumes Orchard's block/index pipeline; ARMv7 consumes its native producers."""
import argparse
from contextlib import redirect_stderr
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

import orchard
from orchard.manifests import validate
from release import audit, build, manifests, smoke_desktop
import test_manifests_and_recovery as publication_fixtures
from test_manifests_and_recovery import release_files
from test_release_architecture import static_elf

SNAPSHOT = Path(orchard.__file__).resolve().parents[2]
HELP = '--root-architecture --platform --device --lwvm --rescue-tools'


class ReleaseContracts(unittest.TestCase):
    def arguments(self, root, architecture, *source):
        argv = ['build', '--release', 'contract-test', '--architecture', architecture,
                '--orchard', str(SNAPSHOT), '--output', str(root / 'output'), *source]
        for name in ('base', 'base-receipt', 'splash', 'logo', 'busybox', 'dropbear', 'dropbearkey',
                     'cursor-tools', 'bluetooth-tools', 'labwc-tools'):
            path = root / name
            if name.endswith('-tools'):
                path.mkdir()
                (path / 'component.txt').write_bytes(b'component')
                (path / 'manifest.json').write_text(json.dumps({'schema': 1, 'files': {
                    'component.txt': hashlib.sha256(b'component').hexdigest()}}))
            elif not path.exists():
                path.write_bytes(static_elf(architecture) if name in build.TOOLS else b'fixture')
            argv.extend(('--' + name, str(path)))
        (root / 'base-receipt').write_text(json.dumps({'release': 'base-fixture', 'architecture': architecture,
            **manifests.receipt(root / 'base')}))
        return argv

    def inputs(self, root):
        bundle = root / 'kernel'
        (bundle / 'dtbs').mkdir(parents=True)
        (bundle / 'dtbs/s5l8942x-p105.dtb').write_bytes(b'dtb')
        (root / 'loader').write_bytes(b'Cascadia')
        for name in (*build.TOOLS, 'orchard-lwvm'):
            (root / name).write_bytes(static_elf('armv7h'))
        row = {'architecture': 'arm', 'image': 'zImage', 'root_format': 'lwvm',
               'kernel': str(bundle), 'boards': {'p105': 's5l8942x-p105'},
               'loader': {'kind': 'cascadia', 'file': str(root / 'loader')},
               'tools': {name: str(root / name) for name in build.TOOLS}}
        row['tools']['lwvm'] = str(root / 'orchard-lwvm')
        document = {'schema': 1, 'architecture': 'arm',
                    'orchard': build.snapshot.revision(SNAPSHOT),
                    'platforms': {'apple-armv7': row}}
        path = root / 'inputs.json'
        path.write_text(json.dumps(document))
        return path, document

    def assemble(self, events):
        def root(base, receipt, output, release, *args, architecture, **kwargs):
            events.append('root')
            output.mkdir()
            (output / 'rootfs.tar.zst').write_bytes(b'root archive')
            result = {'architecture': architecture, 'compression': 'zstd', 'expanded_bytes': 100, 'members': 1,
                      'stamps': {'base': json.loads(receipt.read_text())['release'], 'orchard': release},
                      **{key: value for key, value in manifests.receipt(output / 'rootfs.tar.zst').items()
                         if key != 'file'}}
            (output / 'rootfs.json').write_text(json.dumps(result))
            return result
        return root

    def test_arm64_keeps_the_index_then_block_image_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            events, commands = [], []
            block = {}

            def producer(snapshot, module, *argv, **kwargs):
                nonlocal block
                commands.append((module, argv))
                events.append(module)
                if module == 'orchard.image.platforms_index':
                    _, offered = release_files(output)
                    for layer in offered['platforms'].values():
                        layer['architecture'] = 'arm64'
                    text = ''.join(manifests.table('loaders.' + name, row)
                                   for name, row in offered['loaders'].items())
                    text += manifests.table('install_tools', offered['install_tools'])
                    text += ''.join(manifests.table('platforms.' + name, row)
                                    for name, row in offered['platforms'].items())
                    (output / 'platforms.toml').write_text(text)
                elif module == 'orchard.image.root_image':
                    block = {**manifests.receipt(output / 'root.blocks.zst'), 'compression': 'zstd',
                             'format': 'blocks', 'expanded_bytes': 100, 'members': 3,
                             'map': manifests.receipt(output / 'root.map.json')}
                    (output / 'root-image.json').write_text(json.dumps(block))
                else:
                    self.fail('Unexpected ARM64 producer: ' + module)

            argv = self.arguments(root, 'aarch64', '--orchard-release', 'nightly-test')
            with patch.object(sys, 'argv', argv), patch.object(build, 'build_root', self.assemble(events)), \
                    patch.object(build.snapshot, 'command', producer):
                build.main()
            self.assertEqual(events, ['root', 'orchard.image.platforms_index', 'orchard.image.root_image'])
            document = manifests.tomllib.loads((output / 'release.toml').read_text())
            validate(document, schema=True)
            self.assertEqual(document['root'], block)
            self.assertEqual(document['boot_method'], 'checkm8-pongo')
            self.assertNotIn('architecture', document['platforms']['apple-16k']['layer'])
            self.assertNotIn('boot', document['platforms']['apple-16k'])

    def test_armv7_uses_both_native_lwvm_producers_and_archive_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, _ = self.inputs(root)
            output = root / 'output'
            events, commands = [], []

            def command(snapshot, module, *argv, **kwargs):
                commands.append((module, argv))
                if argv == ('--help',):
                    return subprocess.CompletedProcess([], 0, stdout=HELP)
                events.append(module)
                if module == 'orchard.image.platform':
                    layer = output / 'platform-apple-armv7.tar.gz'
                    layer.write_bytes(b'platform')
                    row = {**manifests.receipt(layer), 'compression': 'gzip', 'expanded_bytes': 10,
                           'members': 1, 'kernel_release': '6.12.0', 'architecture': 'arm', 'boards': ['p105'],
                           'producer_only': 'private build metadata'}
                    receipt = Path(argv[argv.index('--receipt') + 1])
                    receipt.write_text(json.dumps(row))
                elif module == 'orchard.image.recovery':
                    Path(argv[argv.index('--output') + 1]).write_bytes(b'Cascadia recovery')
                else:
                    self.fail('Unexpected ARMv7 producer: ' + module)

            argv = self.arguments(root, 'armv7h', '--inputs', str(inputs))
            with patch.object(sys, 'argv', argv), patch.object(build, 'build_root', self.assemble(events)), \
                    patch.object(build.snapshot, 'command', command):
                build.main()
            self.assertEqual(events, ['root', 'orchard.image.platform', 'orchard.image.recovery'])
            for module, argv in commands:
                if argv == ('--help',):
                    continue
                self.assertEqual(Path(argv[argv.index('--lwvm') + 1]), root / 'orchard-lwvm')
                if module == 'orchard.image.platform':
                    self.assertEqual(argv[argv.index('--rescue-tools') + 1], root)
            document = manifests.tomllib.loads((output / 'release.toml').read_text())
            validate(document, schema=True)
            self.assertNotIn('format', document['root'])
            self.assertNotIn('pongo', document)
            self.assertEqual(document['boot_method'], 'recovery-autogo')
            self.assertEqual(document['root']['file'], 'rootfs.tar.zst')
            self.assertNotIn('producer_only', document['platforms']['apple-armv7']['layer'])
            receipt = json.loads((output / 'build-receipt.json').read_text())
            self.assertEqual(receipt['public_root']['stamps'], {'base': 'base-fixture', 'orchard': 'contract-test'})
            self.assertEqual(receipt['base']['metadata']['release'], 'base-fixture')
            self.assertEqual(receipt['public_root']['sha256'], manifests.sha(output / 'rootfs.tar.zst'))
            self.assertEqual(receipt['components']['cursor']['manifest']['sha256'], manifests.sha(root / 'cursor-tools/manifest.json'))
            self.assertEqual(receipt['components']['labwc']['files']['component.txt']['sha256'], hashlib.sha256(b'component').hexdigest())
            self.assertEqual(len(receipt['omarchy']['tree_sha256']), 64)
            self.assertEqual(len(receipt['omarchy']['commit']), 40)
            self.assertEqual(receipt['orchard']['commit'], build.snapshot.revision(SNAPSHOT)['commit'])
            self.assertEqual(receipt['producer']['buildenv']['sha256'], manifests.sha(SNAPSHOT / 'src/orchard/buildenv.py'))

    def test_missing_recovery_mapper_support_stops_before_root_assembly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, _ = self.inputs(root)
            argv = self.arguments(root, 'armv7h', '--inputs', str(inputs))

            def help(snapshot, module, *argv, **kwargs):
                return subprocess.CompletedProcess([], 0, stdout=HELP if module.endswith('.platform') else '--platform --device')

            with patch.object(sys, 'argv', argv), patch.object(build.snapshot, 'command', help), \
                    patch.object(build, 'build_root') as assemble, redirect_stderr(io.StringIO()) as errors, \
                    self.assertRaises(SystemExit):
                build.main()
            assemble.assert_not_called()
            self.assertIn('orchard.image.recovery lacks', errors.getvalue())
            self.assertIn('--lwvm', errors.getvalue())
            self.assertFalse((root / 'output').exists())

    def test_native_input_guards_check_isa_board_and_root_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, document = self.inputs(root)
            args = argparse.Namespace(architecture='armv7h', orchard=SNAPSHOT)
            row = document['platforms']['apple-armv7']
            (root / 'iw').write_bytes(static_elf('aarch64'))
            with self.assertRaisesRegex(ValueError, 'iw.*ELF'):
                build.platform_inputs(args, 'apple-armv7', document)
            (root / 'iw').write_bytes(static_elf('armv7h'))
            row['root_format'] = 'gpt'
            with self.assertRaisesRegex(ValueError, 'root format differs'):
                build.platform_inputs(args, 'apple-armv7', document)
            row['root_format'] = 'lwvm'
            row['boards']['j1'] = 's5l8945x-j1'
            args.device = 'p105'
            with self.assertRaisesRegex(ValueError, 'one selected board'):
                build.platform_inputs(args, 'apple-armv7', document)

    def test_document_architecture_is_checked_before_native_components(self):
        args = argparse.Namespace(architecture='armv7h', platform=['apple-armv7'], kernel_dir=None)
        document = {'architecture': 'arm64', 'platforms': {'apple-armv7': {'kernel': '/kernel'}}}
        with self.assertRaisesRegex(ValueError, 'Input document architecture differs'):
            build.kernels(args, document)

    def test_old_base_stamp_requires_rebuild_before_assembly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = self.arguments(root, 'aarch64', '--orchard-release', 'nightly-test',
                                  '--base-release', 'base-new-desktop-key')
            with patch.object(sys, 'argv', argv), patch.object(build, 'build_root') as assemble, \
                    redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
                build.main()
            assemble.assert_not_called()
            self.assertIn('rebuild the base component', errors.getvalue())

    def test_inputs_revision_must_match_the_clean_live_orchard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, document = self.inputs(root)
            document['orchard']['commit'] = '0' * 40
            inputs.write_text(json.dumps(document))
            argv = self.arguments(root, 'armv7h', '--inputs', str(inputs))
            with patch.object(sys, 'argv', argv), patch.object(build, 'build_root') as assemble, \
                    redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
                build.main()
            assemble.assert_not_called()
            self.assertIn('inputs revision differs', errors.getvalue())

    def assembly_mutation(self, root, mutation):
        argv = self.arguments(root, 'aarch64', '--orchard-release', 'nightly-test')
        assemble = self.assemble([])

        def changed(*args, **kwargs):
            result = assemble(*args, **kwargs)
            mutation()
            return result

        def files(args):
            block, offered = release_files(args.output)
            (args.output / 'root-image.json').write_text(json.dumps(block))
            return offered

        with patch.object(sys, 'argv', argv), patch.object(build, 'build_root', changed), \
                patch.object(build, 'orchard_files', files), patch.object(build.snapshot, 'command'):
            build.main()

    def test_regular_input_mutation_cannot_be_labeled_by_late_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, 'Consumed input changed'):
                self.assembly_mutation(root, lambda: (root / 'base').write_bytes(b'mutated base'))
            self.assertFalse((root / 'output/build-receipt.json').exists())

    def test_orchard_source_must_stay_unchanged_during_assembly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initial = build.orchard_identity(SNAPSHOT)
            changed = {**initial, 'tree_sha256': '0' * 64}
            with patch.object(build, 'orchard_identity', side_effect=[initial, changed]), \
                    self.assertRaisesRegex(ValueError, 'Orchard source changed'):
                self.assembly_mutation(root, lambda: None)
            self.assertFalse((root / 'output/build-receipt.json').exists())

    def test_arm64_layer_audit_has_no_recovery_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, row = publication_fixtures.LayerAudit().layer(root)
            files = {'boards': ['j71b'], 'layer': {**manifests.receipt(path), **row}}
            with patch.object(audit, 'audit_recovery') as recovery, patch.object(audit, 'audit_runtime') as runtime:
                result, hashes = audit.audit_platform(root / 'release.toml', 'apple-16k', files, set(),
                                                      architecture='aarch64', release='test')
            self.assertEqual(result['boards'], ['j71b'])
            self.assertNotIn('recovery', result)
            self.assertIn('usr/lib/orchard/platform.json', hashes)
            recovery.assert_not_called()
            runtime.assert_not_called()

    def test_lwvm_artifact_audit_requires_matching_native_mapper_and_ssh_tools(self):
        from orchard.image.initramfs import record
        paths = {'bin/orchard-lwvm': 'usr/sbin/orchard-lwvm', 'bin/dropbear': 'usr/sbin/dropbear',
                 'bin/dropbearkey': 'usr/bin/dropbearkey', 'bin/busybox': 'bin/busybox'}
        entries = {name: (stat.S_IFREG | 0o755, static_elf('armv7h')) for name in paths}
        runtime = {'hashes': {target: hashlib.sha256(entries[name][1]).hexdigest()
                              for name, target in paths.items()},
                   'modes': {target: stat.S_IFREG | 0o755 for target in paths.values()}}

        def initrd(contents):
            stream = io.BytesIO()
            for index, (name, (mode, data)) in enumerate(sorted(contents.items()), 1):
                record(stream, index, name, mode, data)
            record(stream, len(contents) + 1, 'TRAILER!!!', 0, b'')
            stream.write(bytes(512))
            return gzip.compress(stream.getvalue(), mtime=0)

        self.assertEqual(set(audit.audit_lwvm_helpers(initrd(entries), runtime, 'armv7h')), set(paths))
        absent = {name: value for name, value in entries.items() if name != 'bin/orchard-lwvm'}
        with self.assertRaisesRegex(ValueError, 'lacks its mapper'):
            audit.audit_lwvm_helpers(initrd(absent), runtime, 'armv7h')
        changed = {**entries, 'bin/orchard-lwvm': (stat.S_IFREG | 0o755, static_elf('armv7h') + b'changed')}
        with self.assertRaisesRegex(ValueError, 'helpers differ'):
            audit.audit_lwvm_helpers(initrd(changed), runtime, 'armv7h')
        foreign = {**entries, 'bin/orchard-lwvm': (stat.S_IFREG | 0o755, static_elf('aarch64'))}
        with self.assertRaisesRegex(ValueError, 'ELF'):
            audit.audit_lwvm_helpers(initrd(foreign), runtime, 'armv7h')
        mode = {**entries, 'bin/dropbear': (stat.S_IFREG | 0o644, static_elf('armv7h'))}
        with self.assertRaisesRegex(ValueError, 'not executable'):
            audit.audit_lwvm_helpers(initrd(mode), runtime, 'armv7h')

    def test_headless_block_release_uses_the_audited_root_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = ['smoke', '--manifest', str(root / 'release.toml'), '--output', str(root / 'evidence')]
            record = {'release': 'test', 'root': {'file': 'root.blocks.zst', 'format': 'blocks'}}
            with patch.object(sys, 'argv', argv), patch.object(smoke_desktop, 'audit', return_value={'root_sha256': 'a' * 64}), \
                    patch.object(smoke_desktop, 'read_release', return_value=record), \
                    patch.object(smoke_desktop.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as run, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                smoke_desktop.main()
            self.assertIn('OMA_ROOT_FILENAME=rootfs.tar.zst', run.call_args.args[0])
            self.assertNotIn('OMA_ROOT_FILENAME=root.blocks.zst', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
