import hashlib
import unittest

from release.j71b.audit import verify_tablet_sudo
from release.j71b.public_root import system_files

POLICY = {'etc/sudoers.d/90-tablet': b'tablet ALL=(ALL:ALL) ALL\n',
          'etc/sudoers.d/omarchy-tzupdate': b'tablet ALL=(root) NOPASSWD: /usr/bin/timedatectl set-timezone *\n'}


class TabletSudoPolicyTests(unittest.TestCase):
    def test_public_overlay_asks_for_the_password(self):
        files = system_files('test-kernel')
        for name, data in POLICY.items():
            self.assertEqual(files[name], (data, 0o440))
        self.assertEqual(sorted(n for n in files if n.startswith('etc/sudoers.d/')), sorted(POLICY))
        self.assertEqual(files['usr/libexec/omarchy-desktop-ready'][1], 0o755)

    def test_auditor_requires_exact_policy_and_root_only_metadata(self):
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in POLICY.items()}
        modes, owners = dict.fromkeys(POLICY, 0o440), dict.fromkeys(POLICY, 0)
        verify_tablet_sudo(hashes, modes, owners, owners)
        name = 'etc/sudoers.d/90-tablet'
        for changed in ({'hashes': {}}, {'hashes': {**hashes, name: 'wrong'}},
                        {'modes': {**modes, name: 0o644}}, {'owners': {**owners, name: 1000}},
                        {'groups': {**owners, name: 1000}},
                        {'hashes': {**hashes, 'etc/sudoers.d/90-tablet-passwordless': 'x'}}):
            with self.subTest(changed=changed):
                args = {'hashes': hashes, 'modes': modes, 'owners': owners, 'groups': owners, **changed}
                with self.assertRaises(ValueError):
                    verify_tablet_sudo(**args)


if __name__ == '__main__':
    unittest.main()
