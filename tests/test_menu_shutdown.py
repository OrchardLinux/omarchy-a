import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
MENU = PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc'


class MenuShutdownTests(unittest.TestCase):
    def check_system_action(self, name, verb):
        entry = re.search(r'"system\.' + name + r'":\s*(\{[^\n]+\})', MENU.read_text())
        action = json.loads(entry.group(1))['action']
        self.assertEqual(action, 'systemctl ' + verb)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = root / 'systemctl'
            command.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CALL_LOG"\n'
                               'echo "test diagnostic" >&2\nexit "$TEST_STATUS"\n')
            command.chmod(0o755)
            log = root / 'calls'
            for status in (0, 1):
                with self.subTest(status=status):
                    env = {**os.environ, 'PATH': str(root), 'CALL_LOG': str(log),
                           'TEST_STATUS': str(status)}
                    result = subprocess.run(['/bin/bash', '-c', action], env=env,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(log.read_text(), verb + '\n')
                    self.assertEqual(result.returncode, status)
                    self.assertIn('test diagnostic', result.stderr)

    def test_shutdown_requests_normal_system_poweroff(self):
        self.check_system_action('shutdown', 'poweroff')

    def test_reboot_requests_normal_system_reboot(self):
        entry = re.search(r'"system\.reboot":\s*(\{[^\n]+\})', MENU.read_text())
        self.assertEqual(json.loads(entry.group(1))['action'], 'orchard-restart')
        script = PROJECT / 'system/overlay/usr/bin/orchard-restart'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); command = root/'systemctl'
            command.write_text('#!/bin/sh\necho "$*" >> "$CALL_LOG"\n'
                               '[ "$1" != start ] || exit "$TEST_STATUS"\n')
            command.chmod(0o755)
            for status in ('0','1'):
                log=root/('log'+status)
                env={**os.environ, 'PATH':str(root), 'CALL_LOG':str(log), 'TEST_STATUS':status}
                result=subprocess.run(['/bin/sh',str(script)],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,int(status))
                self.assertEqual(log.read_text(), 'start orchard-kexec-load.service\n'+('reboot\n' if status=='0' else ''))
                if status=='1': self.assertIn('no hardware reset',result.stderr)


if __name__ == '__main__':
    unittest.main()
