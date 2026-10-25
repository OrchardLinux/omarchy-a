"""Public bootstrap output without network or device access."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'install.sh'


class Bootstrap(unittest.TestCase):
    def run_bootstrap(self, *, fail=False, local_bin_in_path=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        home = Path(temporary.name)
        tools = home / 'test-bin'
        tools.mkdir()
        python = tools / 'python3'
        python.write_text('''#!/bin/bash
if [ "$1" = -c ]; then exit 0; fi
if [ "$1" = -m ] && [ "$2" = venv ]; then
    mkdir -p "$3/bin"
    cat > "$3/bin/python" <<'PIP'
#!/bin/bash
printf '%s\\n' "$*" >> "$HOME/calls"
echo 'pip warning and package download details' >&2
PIP
    cat > "$3/bin/orchard" <<'CLI'
#!/bin/bash
printf '%s\\n' "$*" >> "$HOME/calls"
if [ "$1" = setup-host ] && [ "${FAIL_HOST:-}" = 1 ]; then
    echo 'Install libusb before continuing.' >&2
    exit 7
fi
echo '{"internal": "raw CLI JSON"}'
CLI
    chmod +x "$3/bin/python" "$3/bin/orchard"
    exit 0
fi
exit 9
''')
        python.chmod(0o755)
        path = str(tools) + ':' + os.environ['PATH']
        if local_bin_in_path:
            path = str(home / '.local/bin') + ':' + path
        result = subprocess.run([shutil.which('bash'), str(SCRIPT)], text=True, capture_output=True,
                                env={**os.environ, 'HOME': str(home), 'PATH': path,
                                     'FAIL_HOST': '1' if fail else '0'})
        return home, result

    def test_success_is_quiet_and_registers_both_distributions(self):
        home, result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertNotIn('raw CLI JSON', result.stdout)
        self.assertNotIn('pip warning', result.stdout)
        self.assertIn('✓ Host tools ready', result.stdout)
        self.assertIn('orchard install minimal-linux', result.stdout)
        self.assertNotIn('export PATH', result.stdout)
        calls = (home / 'calls').read_text()
        self.assertIn('--quiet --disable-pip-version-check', calls)
        self.assertIn('distros minimal-linux', calls)
        logs = list((home / '.local/share/orchard/logs').glob('bootstrap-*.log'))
        self.assertEqual(len(logs), 1)
        self.assertIn('raw CLI JSON', logs[0].read_text())
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)

    def test_failure_keeps_actionable_error_and_nonzero_status(self):
        home, result = self.run_bootstrap(fail=True)
        self.assertEqual(result.returncode, 7)
        self.assertIn('Install libusb', result.stderr)
        self.assertIn('Full diagnostic log:', result.stderr)
        self.assertNotIn('Distributions registered', result.stdout)
        self.assertFalse((home / '.local/bin/orchard').exists())

    def test_missing_path_uses_direct_command_instead_of_path_changes(self):
        _, result = self.run_bootstrap(local_bin_in_path=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"$HOME/.local/bin/orchard" install minimal-linux', result.stdout)
        self.assertNotIn('export PATH', result.stdout)


if __name__ == '__main__':
    unittest.main()
