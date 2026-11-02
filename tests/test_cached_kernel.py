"""Which kernels a release uses: every platform orchard's inputs name, or explicit bundles; no builds or devices."""
import argparse
from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import orchard
from release import build

SNAPSHOT = Path(orchard.__file__).resolve().parents[2]
INPUTS = {'platforms': {'apple-16k': {'kernel': '/cache/apple-16k', 'boards': {'j71b': 't8010-j71b'}},
                        'apple-4k': {'kernel': '/cache/apple-4k', 'boards': {'n61': 't7000-n61'}}}}


class CachedKernelTests(unittest.TestCase):
    def args(self, kernel_dir=None, only=None):
        return argparse.Namespace(kernel_dir=kernel_dir, platform=only)

    def test_a_release_covers_every_platform_the_inputs_name(self):
        bundles = build.kernels(self.args(), INPUTS)
        self.assertEqual(sorted(bundles), ['apple-16k', 'apple-4k'])
        self.assertEqual(bundles['apple-16k'], Path('/cache/apple-16k'))

    def test_explicit_bundles_win(self):
        bundles = build.kernels(self.args(['apple-16k=/explicit/16k']), INPUTS)
        self.assertEqual(bundles, {'apple-16k': Path('/explicit/16k'), 'apple-4k': Path('/cache/apple-4k')})

    def test_without_inputs_the_explicit_bundles_are_the_release(self):
        self.assertEqual(build.kernels(self.args(['apple-16k=/explicit/16k'])), {'apple-16k': Path('/explicit/16k')})

    def test_development_builds_may_take_fewer_platforms(self):
        self.assertEqual(build.kernels(self.args(['apple-16k=/explicit/16k'], ['apple-16k']), INPUTS),
                         {'apple-16k': Path('/explicit/16k')})

    def test_unknown_platforms_are_refused(self):
        for args, document in ((self.args(['apple-64k=/x']), INPUTS), (self.args(['/no/platform']), INPUTS),
                               (self.args(None, ['apple-64k']), INPUTS), (self.args(), None)):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'apple-16k|platform'):
                build.kernels(args, document)

    def argv(self, root):
        argv = ['build', '--release', 'test']
        for name in ('base', 'base-receipt', 'loader', 'splash', 'logo', 'pongo', 'busybox', 'dropbear',
                     'dropbearkey', 'wpa-supplicant', 'wpa-cli', 'iw',
                     'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
            path = root / name
            if name.endswith('-tools'):
                path.mkdir()
            elif name != 'output':
                path.write_text('fixture')
            argv += ['--' + name, str(path)]
        return argv + ['--orchard', str(SNAPSHOT)]

    def test_parser_resolves_kernels_before_running_the_assembler(self):
        with tempfile.TemporaryDirectory() as temporary:
            argv = self.argv(Path(temporary))
            with patch.object(sys, 'argv', argv), \
                    patch.object(build, 'kernels', return_value={}) as resolve, \
                    patch.object(build, 'build_root', side_effect=RuntimeError('assembler reached')), \
                    self.assertRaisesRegex(RuntimeError, 'assembler reached'):
                build.main()
            resolve.assert_called_once()
            self.assertIsNone(resolve.call_args.args[0].kernel_dir)

    def test_missing_distro_inputs_fail_before_resolving_kernels(self):
        for name in ('base', 'base-receipt', 'loader', 'splash', 'logo', 'pongo', 'busybox', 'dropbear',
                     'dropbearkey', 'wpa-supplicant', 'wpa-cli', 'iw',
                     'cursor-tools', 'bluetooth-tools', 'labwc-tools'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                argv = self.argv(root)
                path = root / name
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
                with patch.object(sys, 'argv', argv), \
                        patch.object(build, 'kernels') as resolve, \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    build.main()
                self.assertEqual(error.exception.code, 2)
                resolve.assert_not_called()


if __name__ == '__main__':
    unittest.main()
