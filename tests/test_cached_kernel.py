"""Which kernels a release uses: every platform, explicit bundles or orchard's cache; no builds or devices."""
import argparse
from contextlib import redirect_stderr
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from orchard.image import platform
from release import build


class CachedKernelTests(unittest.TestCase):
    def args(self, kernel_dir=None, only=None):
        return argparse.Namespace(kernel_dir=kernel_dir, platform=only)

    def test_a_release_covers_every_platform_from_the_cache(self):
        with patch.object(platform, 'kernel', side_effect=lambda name: Path('/cache') / name) as cached:
            bundles = build.kernels(self.args())
        self.assertEqual(sorted(bundles), platform.platforms())
        self.assertEqual(bundles['apple-16k'], Path('/cache/apple-16k'))
        self.assertEqual(cached.call_count, len(platform.platforms()))

    def test_explicit_bundles_are_not_built(self):
        with patch.object(platform, 'kernel', side_effect=lambda name: Path('/cache') / name) as cached:
            bundles = build.kernels(self.args(['apple-16k=/explicit/16k']))
        self.assertEqual(bundles['apple-16k'], Path('/explicit/16k'))
        self.assertEqual([call.args for call in cached.call_args_list],
                         [(name,) for name in platform.platforms() if name != 'apple-16k'])

    def test_development_builds_may_take_fewer_platforms(self):
        with patch.object(platform, 'kernel') as cached:
            bundles = build.kernels(self.args(['apple-16k=/explicit/16k'], ['apple-16k']))
        self.assertEqual(bundles, {'apple-16k': Path('/explicit/16k')})
        cached.assert_not_called()

    def test_unknown_platforms_are_refused_before_any_build(self):
        for args in (self.args(['apple-64k=/x']), self.args(['/no/platform']), self.args(None, ['apple-64k'])):
            with self.subTest(args=args), patch.object(platform, 'kernel') as cached, \
                    self.assertRaisesRegex(ValueError, 'apple-16k'):
                build.kernels(args)
            cached.assert_not_called()

    def argv(self, root):
        argv = ['build', '--release', 'test']
        for name in ('base', 'base-receipt', 'loader', 'pongo', 'busybox', 'dropbear',
                     'dropbearkey', 'wpa-supplicant', 'wpa-cli', 'iw',
                     'cursor-tools', 'bluetooth-tools', 'labwc-tools', 'output'):
            path = root / name
            if name.endswith('-tools'):
                path.mkdir()
            elif name != 'output':
                path.write_text('fixture')
            argv += ['--' + name, str(path)]
        return argv

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
        for name in ('base', 'base-receipt', 'loader', 'pongo', 'busybox', 'dropbear',
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
