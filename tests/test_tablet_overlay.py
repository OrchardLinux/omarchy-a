from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from release.common import PROJECT
from release.tablet_overlay import BASE_SHELL, changed_since_base, ls_tree, stage, WARM_REQUIRED
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

    def test_warm_stack_follows_kexec_tools_kexec_and_reset_guard(self):
        import release.apply_tablet_overlay as overlay
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'system/overlay/usr/lib/orchard-kexec'))
        import reset
        with tempfile.TemporaryDirectory() as tmp:
            host=Path(tmp)/'host';target=Path(tmp)/'target'
            def path(name): return host/str(name).lstrip('/')
            def guard():
                try: reset.backend(); return True
                except ValueError: return False
            path('/sys/kernel').mkdir(parents=True);path('/sys/kernel/kexec_loaded').write_text('0\n')
            path('/sys/kernel/reboot').mkdir();path('/sys/kernel/reboot/mode').write_text('cold\n')
            node=path('/proc/device-tree/soc/watchdog@1');node.mkdir(parents=True)
            (node/'compatible').write_bytes(b'apple,s8000-wdt\0apple,wdt\0')
            (target/'usr/bin').mkdir(parents=True)
            with patch.object(overlay,'Path',side_effect=path),patch.object(reset,'Path',side_effect=path):
                for tethered in (False,True):  # the same guard orchard-kexec reads
                    (node/'apple,tethered-boot').touch() if tethered else None
                    self.assertEqual(overlay.running_warm_mechanism(),guard())
                self.assertFalse(overlay.target_warm_supported(target))  # no kexec-tools
                (target/'usr/bin/kexec').touch()
                self.assertTrue(overlay.target_warm_supported(target))
                (node/'apple,tethered-boot').unlink()  # J71b and every other board today
                self.assertFalse(overlay.target_warm_supported(target))
                (node/'apple,tethered-boot').touch();path('/sys/kernel/kexec_loaded').unlink()
                self.assertFalse(overlay.target_warm_supported(target))
        self.assertNotIn('device-feature',(Path(overlay.__file__)).read_text())

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

    def test_changes_come_from_the_recorded_base_and_head_alone(self):
        # Only HEAD's tree is read from git, so a shallow checkout without
        # tags (CI) stages the same files as a full clone.
        base=ls_tree(BASE_SHELL.read_text().splitlines())
        (same,(m1,o1)),(edited,(m2,o2)),(chmod,(m3,o3)),(removed,_)=sorted(base.items())[:4]
        head=[f'{m1} blob {o1}\t{same}',f'{m2} blob {"0"*40}\t{edited}',
              f'{"100755" if m3=="100644" else "100644"} blob {o3}\t{chmod}',
              f'100644 blob {"1"*40}\tdesktop/shell/new-file']
        head+=[f'{m} blob {o}\t{p}' for p,(m,o) in sorted(base.items())[4:]]
        with patch('release.tablet_overlay.subprocess.check_output',return_value='\n'.join(head)+'\n') as git:
            self.assertEqual(changed_since_base(),sorted([edited,chmod,removed,'desktop/shell/new-file']))
        self.assertEqual(git.call_args.args[0],['git','ls-tree','-r','HEAD','--','desktop/shell'])

    def test_recorded_base_is_the_v0_2_0_tree(self):
        # A full clone checks the record against the tag; a shallow checkout
        # without tags has nothing to compare with.
        tag=subprocess.run(['git','rev-parse','-q','--verify','v0.2.0^{commit}'],cwd=PROJECT,capture_output=True,text=True)
        if tag.returncode: self.skipTest('v0.2.0 is not in this checkout (shallow clone without tags)')
        listed=subprocess.check_output(['git','ls-tree','-r','v0.2.0','--','desktop/shell'],cwd=PROJECT,text=True)
        self.assertEqual(ls_tree(BASE_SHELL.read_text().splitlines()),ls_tree(listed.splitlines()))
        diff=subprocess.check_output(['git','diff','--name-only','v0.2.0','HEAD','--','desktop/shell'],cwd=PROJECT,text=True)
        self.assertEqual(changed_since_base(),sorted(diff.splitlines()))

if __name__=='__main__':unittest.main()
