"""Both architectures release the same way: orchard's index, then the root as a block image."""
import argparse
from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import orchard
from orchard.manifests import validate
from release import build, manifests, smoke_desktop
from test_manifests_and_recovery import release_files
from test_release_architecture import elf

SNAPSHOT = Path(orchard.__file__).resolve().parents[2]


def armv7_files(output):
    """What orchard's 32-bit index offers, in its shape as assumed here: loaders, install tools, platforms."""
    root, _ = release_files(output)
    for name in ('cascadia-p105.bin', 'install-tools-armv7.tar.gz', 'platform-apple-armv7.tar.gz'):
        (output / name).write_bytes(name.encode())
    # orchard's platforms-armv7.toml: a Cascadia loader per board.
    offered = {'architecture': 'arm', 'loaders': {'cascadia': {'p105': manifests.receipt(output / 'cascadia-p105.bin')}},
               'install_tools': manifests.receipt(output / 'install-tools-armv7.tar.gz'),
               'platforms': {'apple-armv7': {**manifests.receipt(output / 'platform-apple-armv7.tar.gz'),
                                             'compression': 'gzip', 'expanded_bytes': 10, 'members': 2,
                                             'kernel_release': '6.12.0-armv7', 'boards': ['p105']}}}
    return root, offered


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
                path.write_bytes(elf(architecture) if name in ('busybox', 'dropbear', 'dropbearkey') else b'fixture')
            argv.extend(('--' + name, str(path)))
        (root / 'base-receipt').write_text(json.dumps({'release': 'base-fixture', 'architecture': architecture,
                                                       **manifests.receipt(root / 'base')}))
        return argv

    def assemble(self, events):
        def root(base, receipt, output, release, *args, architecture, **kwargs):
            events.append(('root', architecture))
            output.mkdir()
            (output / 'rootfs.tar.zst').write_bytes(b'root archive')
            result = {'architecture': architecture, 'compression': 'zstd', 'expanded_bytes': 100, 'members': 1,
                      **{key: value for key, value in manifests.receipt(output / 'rootfs.tar.zst').items()
                         if key != 'file'}}
            (output / 'rootfs.json').write_text(json.dumps(result))
            return result
        return root

    def release(self, architecture, *source):
        """Run release.build with orchard's producers faked; return its events, commands and manifest."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'output'
            events, commands = [], []

            def producer(snapshot, module, *argv, **kwargs):
                commands.append((module, argv))
                events.append(module)
                if module == 'orchard.image.platforms_index':
                    _, offered = (release_files if architecture == 'aarch64' else armv7_files)(output)
                    loaders = offered['loaders']
                    text = ''.join(manifests.table('loaders.cascadia.' + board, row)
                                   for board, row in loaders.get('cascadia', {}).items())
                    text += ''.join(manifests.table('loaders.' + name, row)
                                    for name, row in loaders.items() if name != 'cascadia')
                    text += manifests.table('install_tools', offered['install_tools'])
                    text += ''.join(manifests.table('platforms.' + name, row)
                                    for name, row in offered['platforms'].items())
                    (output / manifests.INDEXES[architecture]).write_text(text)
                elif module == 'orchard.image.root_image':
                    block = {**manifests.receipt(output / 'root.blocks.zst'), 'compression': 'zstd',
                             'format': 'blocks', 'expanded_bytes': 100, 'members': 3,
                             'map': manifests.receipt(output / 'root.map.json')}
                    (output / 'root-image.json').write_text(json.dumps(block))
                else:
                    self.fail('Unexpected producer: ' + module)

            argv = self.arguments(root, architecture, *source)
            with patch.object(sys, 'argv', argv), patch.object(build, 'build_root', self.assemble(events)), \
                    patch.object(build.snapshot, 'command', producer):
                build.main()
            document = manifests.tomllib.loads((output / 'release.toml').read_text())
            receipt = json.loads((output / 'build-receipt.json').read_text())
            return events, commands, document, receipt

    def test_arm64_keeps_the_index_then_block_image_pipeline(self):
        events, commands, document, receipt = self.release('aarch64', '--orchard-release', 'nightly-test')
        self.assertEqual(events, [('root', 'aarch64'), 'orchard.image.platforms_index', 'orchard.image.root_image'])
        self.assertEqual(commands[0][1][1:], ('--release', 'nightly-test'))
        validate(document, schema=True)
        self.assertEqual(document['boot_method'], 'checkm8-pongo')
        self.assertEqual(document['root']['format'], 'blocks')
        self.assertIn('pongo', document)
        self.assertEqual(receipt['architecture'], 'aarch64')

    def test_armv7_is_a_block_image_release_from_the_32_bit_index(self):
        events, commands, document, receipt = self.release('armv7h', '--orchard-release', 'nightly-test',
                                                           '--platform', 'apple-armv7')
        self.assertEqual(events, [('root', 'armv7h'), 'orchard.image.platforms_index', 'orchard.image.root_image'])
        self.assertEqual(commands[0][1][1:], ('--release', 'nightly-test', '--architecture', 'arm',
                                              '--platform', 'apple-armv7'))
        self.assertEqual(document['root']['format'], 'blocks')
        self.assertEqual(document['boot_method'], 'recovery-autogo')
        self.assertEqual(document['cascadia']['p105']['file'], 'cascadia-p105.bin')
        for absent in ('pongo', 'm1n1', 'logo'):
            self.assertNotIn(absent, document)
        self.assertEqual(document['platforms']['apple-armv7']['boards'], ['p105'])
        self.assertNotIn('boot', document['platforms']['apple-armv7'], 'no recovery')
        self.assertEqual(receipt['architecture'], 'armv7h')

    def test_armv7_from_a_published_build_names_its_platforms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            argv = self.arguments(root, 'armv7h', '--orchard-release', 'nightly-test')
            with patch.object(sys, 'argv', argv), patch.object(build, 'build_root') as assemble, \
                    redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
                build.main()
            assemble.assert_not_called()
            self.assertIn('--platform', errors.getvalue())

    def test_platforms_of_another_architecture_are_refused_before_assembly(self):
        for architecture, platform in (('armv7h', 'apple-16k'), ('aarch64', 'apple-armv7')):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                inputs = root / 'inputs.json'
                inputs.write_text(json.dumps({'orchard': {'commit': 'c' * 40, 'modified': False},
                                              'platforms': {platform: {'kernel': '/unused'}}}))
                argv = self.arguments(root, architecture, '--inputs', str(inputs))
                with patch.object(sys, 'argv', argv), patch.object(build, 'build_root') as assemble, \
                        redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit):
                    build.main()
                assemble.assert_not_called()
                self.assertIn('not a platform of the', errors.getvalue())

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


if __name__ == '__main__':
    unittest.main()
