"""omarchy-channel: the nightly channel's repository in pacman.conf, added above [orchard] and taken out again."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / 'desktop/shell/bin/omarchy-channel'

# pacman.conf as an image has it (system/assemble-rootfs), shortened.
CONF = '''[options]
Architecture = aarch64
SigLevel = Required DatabaseOptional

[orchard]
SigLevel = Optional TrustAll
Server = https://github.com/OrchardLinux/packages/releases/download/repo-$arch

[omarchy]
Server = https://pkgs.omarchy.org/stable/$arch

[core]
Include = /etc/pacman.d/mirrorlist
'''
NIGHTLY = '''[omarchy-a-nightly]
SigLevel = Optional TrustAll
Server = https://github.com/OrchardLinux/omarchy-a/releases/download/pacman-nightly

'''


class Channel(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.conf, self.calls, bin = root / 'pacman.conf', root / 'calls', root / 'bin'
        self.conf.write_text(CONF)
        bin.mkdir()
        self.machine = 'aarch64'
        # The device's commands: sudo runs what it is given (and is recorded), pacman's wrapper only records.
        for name, body in (('sudo', 'echo "sudo $*" >> "$CALLS"\nexec "$@"'),
                           ('omarchy-update-pacman', 'echo "pacman $*" >> "$CALLS"'),
                           ('uname', 'echo "$MACHINE"')):
            (bin / name).write_text('#!/bin/sh\n' + body + '\n')
            (bin / name).chmod(0o755)
        self.env = {**os.environ, 'PATH': f'{bin}:{os.environ["PATH"]}', 'CALLS': str(self.calls),
                    'OMARCHY_PACMAN_CONF': str(self.conf)}

    def channel(self, *args):
        self.calls.write_text('')
        result = subprocess.run(['sh', str(SCRIPT), *args], env={**self.env, 'MACHINE': self.machine},
                                capture_output=True, text=True)
        return result.returncode, self.calls.read_text().splitlines()

    def pacman(self, calls):
        return [call for call in calls if call.startswith('pacman ')]

    def test_nightly_lists_the_channel_above_orchard_and_updates(self):
        code, calls = self.channel('nightly')
        self.assertEqual(code, 0)
        self.assertEqual(self.conf.read_text(), CONF.replace('[orchard]\n', NIGHTLY + '[orchard]\n'))
        self.assertEqual(self.pacman(calls), ['pacman -Syu'])
        self.assertTrue(any(call.startswith('sudo cp ') for call in calls))

    def test_nightly_twice_lists_it_once(self):
        self.channel('nightly')
        code, calls = self.channel('nightly')
        self.assertEqual(code, 0)
        self.assertEqual(self.conf.read_text().count('[omarchy-a-nightly]'), 1)
        # Nothing to change: no root write, only the update.
        self.assertEqual(calls, ['pacman -Syu'])

    def test_stable_takes_it_out_and_goes_back_to_the_release(self):
        self.channel('nightly')
        code, calls = self.channel('stable')
        self.assertEqual(code, 0)
        self.assertEqual(self.conf.read_text(), CONF)
        self.assertEqual(self.pacman(calls), ['pacman -Syuu'])
        code, calls = self.channel('stable')
        self.assertEqual((code, calls), (0, ['pacman -Syuu']))
        self.assertEqual(self.conf.read_text(), CONF)

    def test_no_nightly_package_for_another_architecture(self):
        self.machine = 'armv7l'
        code, calls = self.channel('nightly')
        self.assertNotEqual(code, 0)
        self.assertEqual((calls, self.conf.read_text()), ([], CONF))

    def test_without_orchard_or_a_channel_nothing_changes(self):
        self.conf.write_text(CONF.replace('[orchard]', '[other]'))
        code, calls = self.channel('nightly')
        self.assertNotEqual(code, 0)
        self.assertEqual(calls, [])
        for args in ((), ('beta',), ('nightly', 'stable')):
            with self.subTest(args=args):
                code, calls = self.channel(*args)
                self.assertEqual((code, calls), (2, []))

    def test_a_command_of_the_menu_s_kind(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        text = SCRIPT.read_text()
        self.assertTrue(text.startswith('#!/bin/sh\n'))
        self.assertRegex(text, r'(?m)^# omarchy:summary=')
        self.assertRegex(text, r'(?m)^# omarchy:requires-sudo=true$')


if __name__ == '__main__':
    unittest.main()
