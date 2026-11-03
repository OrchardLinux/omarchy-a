"""system/rank-mirrors: the fastest Arch Linux ARM mirrors first, failures left out."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'system/rank-mirrors'

# A curl stand-in: the speed (bytes/s) and size each mirror answers with,
# keyed by host; anything unlisted fails like an unreachable mirror.
CURL = '''#!/bin/sh
for arg; do url=$arg; done
host=${url#https://}; host=${host%%/*}
case $host in
  ca.us.mirror.archlinuxarm.org) printf '700000 2097152' ;;
  de3.mirror.archlinuxarm.org) printf '900000 2097152' ;;
  mirrors.ustc.edu.cn) printf '300000 2097152' ;;
  mirrors.tuna.tsinghua.edu.cn) printf '5000000 1000' ;;  # cut short
  *) exit 28 ;;
esac
'''

BASH = shutil.which('bash')


def bash_major():
    out = subprocess.run([BASH, '-c', 'echo ${BASH_VERSINFO[0]}'], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


@unittest.skipUnless(BASH and bash_major() >= 4, 'needs bash 4+ (mapfile), as in the builders')
class RankMirrors(unittest.TestCase):
    def run_script(self, curl):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'curl').write_text(curl)
            (root / 'curl').chmod(0o755)
            mirrorlist = root / 'mirrorlist'
            mirrorlist.write_text('Server = https://old.example/$arch/$repo\n')
            env = {**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}'}
            subprocess.run([BASH, str(SCRIPT), str(mirrorlist)], env=env, check=True,
                           capture_output=True, timeout=60)
            return [line for line in mirrorlist.read_text().splitlines()
                    if line.startswith('Server')]

    def test_fastest_first_and_failures_left_out(self):
        self.assertEqual(self.run_script(CURL), [
            'Server = https://de3.mirror.archlinuxarm.org/$arch/$repo',
            'Server = https://ca.us.mirror.archlinuxarm.org/$arch/$repo',
            'Server = https://mirrors.ustc.edu.cn/archlinuxarm/$arch/$repo',
        ])

    def test_keeps_the_list_when_no_mirror_answers(self):
        self.assertEqual(self.run_script('#!/bin/sh\nexit 6\n'),
                         ['Server = https://old.example/$arch/$repo'])


class Copies(unittest.TestCase):
    def test_desktop_copy_is_identical(self):
        # desktop/rank-mirrors exists for the desktop builders' build context
        self.assertEqual((ROOT / 'desktop/rank-mirrors').read_bytes(), SCRIPT.read_bytes())


if __name__ == '__main__':
    unittest.main()
