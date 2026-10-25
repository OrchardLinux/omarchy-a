import hashlib
import unittest

from release.j71b.audit import verify_tablet_sudo
from release.j71b.public_root import system_files


class TabletSudoPolicyTests(unittest.TestCase):
    def test_public_overlay_contains_explicit_tablet_policy(self):
        files = system_files('test-kernel')
        data, mode = files['etc/sudoers.d/90-tablet-passwordless']
        self.assertEqual(data, b'tablet ALL=(ALL:ALL) NOPASSWD: ALL\n')
        self.assertEqual(mode, 0o440)
        self.assertEqual(files['usr/libexec/omarchy-desktop-ready'][1], 0o755)

    def test_auditor_requires_exact_policy_and_root_only_metadata(self):
        name = 'etc/sudoers.d/90-tablet-passwordless'
        digest = hashlib.sha256(b'tablet ALL=(ALL:ALL) NOPASSWD: ALL\n').hexdigest()
        verify_tablet_sudo({name: digest}, {name: 0o440}, {name: 0}, {name: 0})
        for hashes, modes, owners, groups in (
                ({}, {}, {}, {}),
                ({name: 'wrong'}, {name: 0o440}, {name: 0}, {name: 0}),
                ({name: digest}, {name: 0o644}, {name: 0}, {name: 0}),
                ({name: digest}, {name: 0o440}, {name: 1000}, {name: 0}),
                ({name: digest}, {name: 0o440}, {name: 0}, {name: 1000})):
            with self.subTest(modes=modes, owners=owners, groups=groups):
                with self.assertRaises(ValueError):
                    verify_tablet_sudo(hashes, modes, owners, groups)
