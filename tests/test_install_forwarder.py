"""The repository's install.sh forwards to the latest release's installer. No network or device."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'install.sh'


class Forwarder(unittest.TestCase):
    def test_runs_the_latest_release_install_sh_with_its_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'curl').write_text('#!/bin/sh\n'
                                       'while [ $# -gt 1 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
                                       'printf "%s\\n" "$1" > "$ROOT/url"\n'
                                       'printf \'printf "%%s\\\\n" "$@" > "$ROOT/arguments"\\n\' > "$out"\n')
            (root / 'curl').chmod(0o755)
            environment = {**os.environ, 'ROOT': str(root), 'PATH': f'{root}{os.pathsep}{os.defpath}'}
            subprocess.run(['sh', str(SCRIPT), 'omarchy-a', '--verbose'], check=True, env=environment)
            self.assertEqual((root / 'url').read_text().strip(),
                             'https://github.com/OrchardLinux/omarchy-a/releases/latest/download/install.sh')
            self.assertEqual((root / 'arguments').read_text().split(), ['omarchy-a', '--verbose'])


if __name__ == '__main__':
    unittest.main()
