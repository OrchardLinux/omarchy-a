"""The release build refuses missing inputs before it assembles anything."""
from contextlib import redirect_stderr
import io
import json
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import orchard
from release import build

SNAPSHOT = Path(orchard.__file__).resolve().parents[2]
INPUTS = ('base', 'base-receipt', 'splash', 'logo', 'busybox', 'dropbear', 'dropbearkey',
          'cursor-tools', 'bluetooth-tools', 'labwc-tools')


class ReleaseInputs(unittest.TestCase):
    def argv(self, root, *source):
        argv = ['build', '--release', 'test', *source, '--output', str(root / 'output')]
        for name in INPUTS:
            path = root / name
            if name.endswith('-tools'):
                path.mkdir()
                (path / 'manifest.json').write_text(json.dumps({'schema': 1, 'files': {}}))
            else:
                path.write_text('fixture')
            argv += ['--' + name, str(path)]
        (root / 'base-receipt').write_text(json.dumps({'release': 'base-fixture',
            'bytes': (root / 'base').stat().st_size, 'sha256': hashlib.sha256((root / 'base').read_bytes()).hexdigest()}))
        return argv + ['--orchard', str(SNAPSHOT)]

    def test_the_root_comes_first_then_orchards_files(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(build, 'build_root', side_effect=RuntimeError('assembler reached')), \
                patch.object(sys, 'argv', self.argv(Path(temporary), '--orchard-release', 'nightly-1')), \
                self.assertRaisesRegex(RuntimeError, 'assembler reached'):
            build.main()

    def test_missing_distro_inputs_fail_before_assembling(self):
        for name in INPUTS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                argv = self.argv(root, '--orchard-release', 'nightly-1')
                path = root / name
                shutil.rmtree(path) if path.is_dir() else path.unlink()
                with patch.object(sys, 'argv', argv), patch.object(build, 'build_root') as assemble, \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    build.main()
                self.assertEqual(error.exception.code, 2)
                assemble.assert_not_called()

    def test_a_release_names_where_orchards_files_come_from(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()), \
                patch.object(sys, 'argv', self.argv(Path(temporary))), self.assertRaises(SystemExit):
            build.main()


if __name__ == '__main__':
    unittest.main()
