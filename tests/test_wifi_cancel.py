from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

MODEL = Path(__file__).resolve().parents[1] / 'desktop/shell/shell/plugins/panels/network/Model.js'


@unittest.skipUnless(shutil.which('node'), 'node is required for the network model')
class WifiCancelTests(unittest.TestCase):
    # A tap on the network that is connecting stops it: the device's
    # activating connection goes down; a link that just came up stays.
    def run_cancel(self, state):
        script = subprocess.run(['node', '-e', 'process.stdout.write(require(process.argv[1]).cancelConnectScript)', str(MODEL)],
                                capture_output=True, text=True, check=True).stdout
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp, 'log')
            nmcli = Path(tmp, 'nmcli')
            nmcli.write_text(f'''#!/bin/bash
echo "$*" >> {log}
case "$*" in
  "-g GENERAL.STATE device show wlan0") echo "{state}" ;;
  "-g GENERAL.CON-UUID device show wlan0") echo "1234-uuid" ;;
esac
''')
            nmcli.chmod(0o755)
            env = dict(os.environ, PATH=f'{tmp}:{os.environ["PATH"]}')
            subprocess.run(['bash', '-c', script, 'nmcli-cancel', 'wlan0'], env=env, check=True)
            return log.read_text().splitlines()

    def test_a_connect_under_way_goes_down(self):
        self.assertIn('connection down uuid 1234-uuid', self.run_cancel('50 (connecting (configuring))'))

    def test_a_finished_connect_stays_up(self):
        self.assertNotIn('connection down uuid 1234-uuid', self.run_cancel('100 (connected)'))


if __name__ == '__main__':
    unittest.main()
