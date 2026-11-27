"""A release's install.sh installs the orchard command and runs `orchard install` for that release. No network or device."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from release import install_script

INDEX = 'https://github.com/OrchardLinux/omarchy-a/releases/download/v9.9.9/index.toml'


class InstallScript(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'log'
        # curl prints a script that "installs" the command; the command records how it was called.
        (self.root / 'command').write_text('#!/bin/sh\nprintf "orchard %s\\n" "$*" >> "$LOG"\n')
        (self.root / 'tools-install.sh').write_text('cp "$HOME/command" "$ORCHARD_BIN/orchard"; chmod 755 "$ORCHARD_BIN/orchard"\n')
        (self.bin / 'curl').write_text('#!/bin/sh\nprintf "curl %s\\n" "$*" >> "$LOG"\ncat "$HOME/tools-install.sh"\n')
        (self.bin / 'curl').chmod(0o755)
        self.script = install_script.write(self.root / 'install.sh', INDEX, INDEX.replace('index.toml', 'install.sh'))

    def run_script(self, *arguments, script=None):
        return subprocess.run(['sh', str(script or self.script), *arguments], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, start_new_session=True,
                              env={'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.root), 'LOG': str(self.log),
                                   'ORCHARD_BIN': str(self.bin)})

    def test_installs_the_command_then_installs_this_release_with_the_arguments(self):
        result = self.run_script('--ibss')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(),
                         ['curl -fsSL https://raw.githubusercontent.com/OrchardLinux/tools/main/install.sh',
                          f'orchard install {INDEX} --ibss'])

    def test_next_to_a_local_build_it_installs_that_build(self):
        local = self.root / 'release'
        local.mkdir()
        (local / 'index.toml').write_text('')
        script = install_script.write(local / 'install.sh', INDEX, 'install.sh')
        self.assertEqual(self.run_script(script=script).returncode, 0)
        self.assertEqual(self.log.read_text().splitlines()[-1], f'orchard install {local}/index.toml')

    def test_only_plain_urls_are_written_into_the_script(self):
        with self.assertRaises(ValueError):
            install_script.write(self.root / 'x.sh', "x'; rm -rf ~; '", 'install.sh')


if __name__ == '__main__':
    unittest.main()
