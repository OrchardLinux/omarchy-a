from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from release.tablet_overlay import stage, WARM_REQUIRED
from release.apply_tablet_overlay import apply, verified

class TabletOverlay(unittest.TestCase):
    def bundle(self,root):
        pkg=root/'package';pkg.write_bytes(b'fixture: no package manager runs in a host root')
        output=root/'bundle'; stage(output,pkg); return output

    def test_dry_run_does_not_create_any_target_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=self.bundle(root);target=root/'target';target.mkdir()
            apply(bundle,target,False)
            self.assertEqual(list(target.iterdir()),[])

    def test_installs_every_hash_and_preserves_replaced_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=self.bundle(root);target=root/'target';target.mkdir()
            old=target/'usr/local/bin/omarchy-keyboard';old.parent.mkdir(parents=True)
            old.symlink_to('/must-not-follow')
            with patch('release.apply_tablet_overlay.target_warm_supported',return_value=True):
                apply(bundle,target,True)
            manifest,files=verified(bundle)
            for name,data in files.items():
                if name.startswith('packages/'): continue
                self.assertEqual((target/name).read_bytes(),data)
                self.assertEqual((target/name).stat().st_mode&0o777,manifest['files'][name]['mode'])
            backup=next((target/'var/lib/omarchy-a/port-backups').iterdir())
            self.assertEqual((backup/'files/usr/local/bin/omarchy-keyboard').readlink(),Path('/must-not-follow'))
            self.assertTrue((target/'usr/lib/systemd/system/omarchy-powerd.service').exists())

    def test_tampered_hash_and_symlink_parent_refuse_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=self.bundle(root);target=root/'target';target.mkdir()
            (target/'usr').symlink_to(root/'escape')
            with self.assertRaises(ValueError): apply(bundle,target,True)
            self.assertFalse((root/'escape').exists())
            (bundle/'overlay.tar.gz').write_bytes(b'bad')
            with self.assertRaises(ValueError): verified(bundle)

    def test_manifest_has_every_unit_tool_hook_and_polkit_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle=self.bundle(Path(tmp));manifest,files=verified(bundle)
            self.assertTrue(WARM_REQUIRED <= files.keys())
            self.assertTrue(WARM_REQUIRED <= set(manifest['warm_restart']['files']))
            self.assertIn(b'"action":"orchard-restart"',files[manifest['warm_restart']['menu']])

    def test_unqualified_target_gets_no_partial_restart_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle=self.bundle(root);target=root/'target';target.mkdir()
            apply(bundle,target,True)
            manifest,files=verified(bundle)
            for name in manifest['warm_restart']['files']:
                self.assertFalse((target/name).exists(),name)
            menu=(target/manifest['warm_restart']['menu']).read_bytes()
            self.assertIn(b'"action":"systemctl reboot"',menu)
            self.assertNotIn(b'"action":"orchard-restart"',menu)

if __name__=='__main__':unittest.main()
