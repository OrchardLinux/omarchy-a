"""system/rank-mirrors: the fastest Arch Linux ARM mirrors first, failures left out,
the official mirror always last; system/pacman-download: bounded download
attempts that move on to the next mirror."""
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
            'Server = https://mirror.archlinuxarm.org/$arch/$repo',
        ])

    def test_official_mirror_once_when_it_ranks(self):
        curl = CURL.replace('  *) exit 28', '  mirror.archlinuxarm.org) printf \'800000 2097152\' ;;\n  *) exit 28')
        self.assertEqual(self.run_script(curl), [
            'Server = https://de3.mirror.archlinuxarm.org/$arch/$repo',
            'Server = https://mirror.archlinuxarm.org/$arch/$repo',
            'Server = https://ca.us.mirror.archlinuxarm.org/$arch/$repo',
            'Server = https://mirrors.ustc.edu.cn/archlinuxarm/$arch/$repo',
        ])

    def test_keeps_the_list_when_no_mirror_answers(self):
        self.assertEqual(self.run_script('#!/bin/sh\nexit 6\n'),
                         ['Server = https://old.example/$arch/$repo'])


DOWNLOAD = ROOT / 'system/pacman-download'
MIRRORS = ['https://stall.example/$arch/$repo', 'https://broken.example/$arch/$repo',
           'https://good.example/$arch/$repo']

# A pacman stand-in that behaves like the first mirror of the list: it hangs
# until interrupted on stall.example, fails on broken.example and succeeds
# elsewhere. Every call appends "ARGS | first mirror | outcome" to the log.
PACMAN = r'''#!/usr/bin/env bash
first=$(sed -n 's/^Server = //p' "$PACMAN_DOWNLOAD_MIRRORLIST" | head -n 1)
case $first in
  *stall.example*)
    trap 'kill $!; echo "$* | $first | interrupted" >> "$LOG"; exit 130' INT
    sleep 30 & wait ;;
  *broken.example*) echo "$* | $first | failed" >> "$LOG"; exit 1 ;;
  *) echo "$* | $first | ok" >> "$LOG" ;;
esac
'''


@unittest.skipUnless(BASH and shutil.which('timeout'), 'needs bash and timeout, as in the builders')
class PacmanDownload(unittest.TestCase):
    def run_script(self, attempts=4):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pacman').write_text(PACMAN)
            (root / 'pacman').chmod(0o755)
            mirrorlist = root / 'mirrorlist'
            mirrorlist.write_text('# ranked\n' + ''.join(f'Server = {m}\n' for m in MIRRORS))
            env = {**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}', 'LOG': str(root / 'log'),
                   'PACMAN_DOWNLOAD_MIRRORLIST': str(mirrorlist), 'PACMAN_DOWNLOAD_SECONDS': '1',
                   'PACMAN_DOWNLOAD_ATTEMPTS': str(attempts)}
            result = subprocess.run([BASH, str(DOWNLOAD), '-Sy', '--noconfirm', 'python'], env=env,
                                    capture_output=True, text=True, timeout=60)
            return (result.returncode, (root / 'log').read_text().splitlines(),
                    [line for line in mirrorlist.read_text().splitlines() if line.startswith('Server')])

    def test_stalled_and_failing_mirrors_hand_over_to_the_next(self):
        status, log, servers = self.run_script()
        self.assertEqual(status, 0)
        self.assertEqual(log, [
            '-Sy --noconfirm python --downloadonly | https://stall.example/$arch/$repo | interrupted',
            '-Sy --noconfirm python --downloadonly | https://broken.example/$arch/$repo | failed',
            '-Sy --noconfirm python --downloadonly | https://good.example/$arch/$repo | ok',
        ])
        self.assertEqual(servers, [f'Server = {m}' for m in MIRRORS[2:] + MIRRORS[:2]])

    def test_gives_up_after_the_last_attempt(self):
        status, log, servers = self.run_script(attempts=2)
        self.assertEqual(status, 1)
        self.assertEqual([line.rsplit(' | ', 1)[1] for line in log], ['interrupted', 'failed'])
        # The list stays rotated past the mirrors that failed this time.
        self.assertEqual(servers[0], f'Server = {MIRRORS[1]}')


class Copies(unittest.TestCase):
    def test_desktop_copies_are_identical(self):
        # desktop/ has copies for the desktop builders' build context
        for name in ('rank-mirrors', 'pacman-download'):
            self.assertEqual((ROOT / 'desktop' / name).read_bytes(), (ROOT / 'system' / name).read_bytes(), name)

    def test_no_download_timeout_override(self):
        # pacman's stall timeout hands a silent download to the next mirror
        for name in ('system/install-toolchain', 'desktop/install-toolchain'):
            self.assertIn("sed -i '/^DisableDownloadTimeout/d' /etc/pacman.conf", (ROOT / name).read_text())


if __name__ == '__main__':
    unittest.main()
