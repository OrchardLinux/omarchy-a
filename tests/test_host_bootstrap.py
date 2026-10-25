"""Small bootstrap: pip from release requirements; host logic stays in the CLI."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'install.sh'


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.home = self.root / 'home with spaces'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.defpath,
                        TEST_ROOT=str(self.root))
        python = self.bin / 'python3'
        python.write_text('''#!/bin/sh
[ "$1" != -c ] || exit 0
[ "$1" = -m ] && [ "$2" = venv ] || exit 1
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'PIP'
#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_ROOT/calls"
[ "${FAIL_PIP:-0}" = 0 ]
PIP
cat > "$3/bin/orchard" <<'CLI'
#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_ROOT/calls"
[ "$1" != setup-host ] || [ "${FAIL_SETUP:-0}" = 0 ]
CLI
chmod +x "$3/bin/python" "$3/bin/orchard"
''')
        python.chmod(0o755)

    def run_setup(self):
        return subprocess.run(['bash', str(SCRIPT)], env=self.env, text=True,
                              capture_output=True, timeout=10)

    def calls(self):
        return (self.root / 'calls').read_text().splitlines()

    def test_syntax(self):
        subprocess.run(['bash', '-n', str(SCRIPT)], check=True)

    def test_installs_latest_requirements_sets_up_host_and_registers(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [
            '-m pip install --upgrade --only-binary=:all: -r https://github.com/OrchardLinux/cli/releases/latest/download/requirements.txt',
            'setup-host',
            'distros omarchy-a https://github.com/OrchardLinux/omarchy-a/releases/latest/download/index.toml',
        ])
        self.assertIn('Resize APFS', result.stdout)

    def test_rerun_uses_upgrade_and_same_environment(self):
        self.assertEqual(self.run_setup().returncode, 0)
        target = (self.home / '.local/bin/orchard').resolve()
        self.assertEqual(self.run_setup().returncode, 0)
        self.assertEqual((self.home / '.local/bin/orchard').resolve(), target)
        self.assertEqual(sum('pip install --upgrade' in row for row in self.calls()), 2)

    def test_failed_pip_stops_before_host_setup(self):
        self.env['FAIL_PIP'] = '1'
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls()), 1)
        self.assertNotIn('Next:', result.stdout)

    def test_failed_host_setup_stops_before_registration(self):
        self.env['FAIL_SETUP'] = '1'
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls()[-1], 'setup-host')
        self.assertNotIn('Next:', result.stdout)

    def test_piped_entry_point(self):
        result = subprocess.run(['bash'], input=SCRIPT.read_text(), env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.calls()[-1].startswith('distros omarchy-a '))


if __name__ == '__main__':
    unittest.main()
