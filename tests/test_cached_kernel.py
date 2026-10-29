"""Distro-owned resolution of optional kernel inputs; no builds or devices."""
import argparse
from contextlib import redirect_stderr
import io
import itertools
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from release.j71b import build


class CachedKernelTests(unittest.TestCase):
    def args(self, supplied=(False, False, False)):
        return argparse.Namespace(**{
            name: Path('/explicit') / name if present else None
            for name, present in zip(('kernel', 'dtbs', 'modules_dir'), supplied)
        }, loader=Path('/branded/loader'), pongo=Path('/branded/pongo'))

    def test_omitted_bundle_uses_generic_builder_and_preserves_branding(self):
        api = ModuleType('orchard_cli.build')
        api.prepare_kernel = Mock(return_value=Path('/shared/kernel'))
        api.configured_device = Mock(return_value='new-board')
        args = self.args()
        with patch.dict(sys.modules, {'orchard_cli.build': api}):
            build.resolve_kernel(args)
        api.configured_device.assert_called_once_with(build.PROJECT)
        api.prepare_kernel.assert_called_once_with(device='new-board')
        self.assertEqual(args.kernel, Path('/shared/kernel/Image.gz'))
        self.assertEqual(args.dtbs, Path('/shared/kernel/dtbs'))
        self.assertEqual(args.modules_dir, Path('/shared/kernel/lib/modules'))
        self.assertEqual(args.loader, Path('/branded/loader'))
        self.assertEqual(args.pongo, Path('/branded/pongo'))

    def test_explicit_bundle_does_not_import_cached_builder(self):
        args = self.args((True, True, True))
        before = vars(args).copy()
        with patch.dict(sys.modules, {'orchard_cli.build': None}):
            build.resolve_kernel(args)
        self.assertEqual(vars(args), before)

    def test_partial_bundle_is_rejected_without_importing_builder(self):
        for supplied in itertools.product((False, True), repeat=3):
            if not any(supplied) or all(supplied):
                continue
            with self.subTest(supplied=supplied), \
                    patch.dict(sys.modules, {'orchard_cli.build': None}), \
                    self.assertRaisesRegex(ValueError, 'together'):
                build.resolve_kernel(self.args(supplied))

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

    def test_parser_accepts_omitted_bundle_before_running_existing_assembler(self):
        with tempfile.TemporaryDirectory() as temporary:
            argv = self.argv(Path(temporary))
            with patch.object(sys, 'argv', argv), \
                    patch.object(build, 'resolve_kernel') as resolve, \
                    patch.object(build, 'build_root', side_effect=RuntimeError('assembler reached')), \
                    self.assertRaisesRegex(RuntimeError, 'assembler reached'):
                build.main()
            resolve.assert_called_once()
            self.assertIsNone(resolve.call_args.args[0].kernel)

    def test_missing_distro_inputs_fail_before_resolving_kernel(self):
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
                        patch.object(build, 'resolve_kernel') as resolve, \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    build.main()
                self.assertEqual(error.exception.code, 2)
                resolve.assert_not_called()
