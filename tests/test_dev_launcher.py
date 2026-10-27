"""Checkout launcher tests with fake uv/git: no environment setup or device I/O."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'orchard', self.root / 'orchard')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'uv.log'
        self.git_log = self.root / 'git.log'
        self.write_executable('uv', 'printf "%s\\n" "$UV_PROJECT_ENVIRONMENT" "$@" > "$LAUNCH_LOG"\n')
        self.write_executable('git', 'printf "%s\\n" "$@" >> "$GIT_LOG"\n'
                              'for member; do :; done\n'
                              'mkdir -p "$FAKE_ROOT/$member"\n'
                              ': > "$FAKE_ROOT/$member/pyproject.toml"\n')
        for member in ('cli', 'hardware'):
            (self.root / member).mkdir()
            (self.root / member / 'pyproject.toml').write_text('local edits\n')

    def write_executable(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\nset -eu\n' + body)
        path.chmod(0o755)

    def launch(self, *arguments):
        return subprocess.run(['sh', str(self.root / 'orchard'), *arguments], cwd=self.bin,
                              env={**os.environ, 'PATH': f'{self.bin}:/usr/bin:/bin',
                                   'LAUNCH_LOG': str(self.log), 'GIT_LOG': str(self.git_log),
                                   'FAKE_ROOT': str(self.root),
                                   'UV_PROJECT_ENVIRONMENT': '/some/other/environment'},
                              capture_output=True, text=True)

    def test_local_project_environment_and_argument_forwarding(self):
        result = self.launch('build', 'directory with spaces', '--modules')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(),
                         [str(self.root / '.venv'), 'run', '--project', str(self.root),
                          'orchard', 'build', 'directory with spaces', '--modules'])
        self.assertFalse(self.git_log.exists())

    def test_only_missing_submodule_is_initialized(self):
        (self.root / 'cli/pyproject.toml').unlink()
        result = self.launch('--version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git_log.read_text().splitlines(),
                         ['-C', str(self.root), 'submodule', 'update', '--init', '--', 'cli'])
        self.assertEqual((self.root / 'hardware/pyproject.toml').read_text(), 'local edits\n')

    def test_exit_status_is_preserved(self):
        self.write_executable('uv', 'exit 7\n')
        self.assertEqual(self.launch('--version').returncode, 7)


class ExampleInitTests(unittest.TestCase):
    def test_ram_examples_do_not_require_j71b(self):
        project = Path(__file__).resolve().parents[1]
        for name in ('minimal-boot', 'charger-001'):
            with self.subTest(example=name):
                script = project / 'examples' / name / 'init'
                source = script.read_text()
                self.assertNotIn('apple,j71b', source)
                self.assertNotIn('Wrong device', source)
                subprocess.run(['sh', '-n', str(script)], check=True)


if __name__ == '__main__':
    unittest.main()
