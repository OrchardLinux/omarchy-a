"""Host-only warm restart state transitions. No sysfs/device access."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
LIB=ROOT/'system/overlay/usr/lib/orchard-kexec'
sys.path.insert(0,str(LIB))
import device
import cli
import diagnostics
import health

class WarmRestart(unittest.TestCase):
    def test_default_bls_changes_after_update(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(device,'BOOT',Path(tmp)):
            p=Path(tmp);(p/'loader').mkdir();(p/'loader/loader.conf').write_text('default orchard-*\n')
            es=[(p/'orchard-1.conf',{'sort-key':['orchard'],'version':['1']}),
                (p/'orchard-2.conf',{'sort-key':['orchard'],'version':['2']})]
            self.assertEqual(device.select_entry(es)[0].stem,'orchard-2')
            self.assertEqual(device.select_entry(es,'orchard-1')[0].stem,'orchard-1')
            with self.assertRaises(ValueError):device.select_entry(es,'../bad')

    def test_updated_bls_assets_load_with_immutable_running_pristine(self):
        import gzip
        import importlib.machinery
        import shutil
        from types import SimpleNamespace
        fdt=importlib.machinery.SourceFileLoader('warm_fixture_fdt',str(LIB/'fdt-merge')).load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);boot=root/'boot';running=root/'run';stage=root/'stage'
            for p in (boot/'loader/entries',running,stage):p.mkdir(parents=True)
            tree=fdt.Node('');tree.props['compatible']=b'apple,j71t\0'
            dt=fdt.serialize(tree,[],0)
            (running/'pristine.dtb').write_bytes(dt);(running/'boot-id').write_text('boot-id')
            (boot/'loader/entries/default.conf').write_text('linux /linux\ninitrd /initrd\ndevicetree /board.dtb\noptions root=PARTUUID=abcd rw\n')
            (boot/'board.dtb').write_bytes(dt);(boot/'initrd').write_bytes(b'new-matching-initrd')
            shutil.copyfile(LIB/'fdt-merge',stage/'fdt-merge')
            pseudo={}
            for name,value in [('/sys/devices/system/cpu/possible','0'),('/proc/cmdline','root=PARTUUID=abcd rw'),
                               ('/proc/sys/kernel/random/boot_id','boot-id'),('/sys/kernel/kexec_loaded','1')]:
                path=root/('pseudo'+str(len(pseudo)));path.write_text(value);pseudo[name]=path
            def paths(name):
                if str(name).startswith(('/proc/','/sys/')):
                    self.assertIn(str(name),pseudo);return pseudo[str(name)]
                return Path(name)
            captured=[]
            expected_loader=['file']
            def run(*args,**kwargs):
                if args[0]=='uname':return SimpleNamespace(stdout='7.3-old\n')
                if args[0]=='python3':
                    self.assertEqual(args[args.index('--old')+1],str(running/'pristine.dtb'))
                    (stage/'merged.dtb').write_bytes(dt)
                elif args[0]=='kexec':
                    self.assertEqual(args[1],'-s' if expected_loader[0]=='file' else '-c')
                    self.assertEqual(any(a.startswith('--dtb=') for a in args),expected_loader[0]=='legacy')
                    captured.append((stage/'Image').read_bytes())
                return SimpleNamespace(stdout='')
            with patch.object(device,'BOOT',boot),patch.object(device,'RUN',running),\
                 patch.object(device,'Path',side_effect=paths),patch.object(cli,'Path',side_effect=paths),\
                 patch.object(device,'run',side_effect=run),patch.object(device.shutil,'which',return_value='/tool'),\
                 patch.object(device,'guard_outgoing',return_value='guarded'):
                for release in ('7.3-update1','7.4-update2'):
                    image=bytearray(64);image[56:60]=b'ARM\x64';image+=b'Linux version '+release.encode()+b' (fixture)\0'
                    (boot/'linux').write_bytes(gzip.compress(image))
                    plan=device.prepare(stage,False)
                    self.assertEqual(plan['release'],release)
                    self.assertEqual(plan['loader'],'file')
                    cli.load(stage)
                    self.assertEqual(captured[-1],image)
                    self.assertEqual((running/'pristine.dtb').read_bytes(),dt)
                    self.assertFalse((stage/'Image').exists())
                # Changed pristine DT must merge runtime fixups and use legacy.
                tree.props['model']=b'updated board model\0'
                (boot/'board.dtb').write_bytes(fdt.serialize(tree,[],0))
                expected_loader[0]='legacy'
                plan=device.prepare(stage,False)
                self.assertEqual(plan['loader'],'legacy')
                cli.load(stage)

    def test_explicit_loader_and_failure_policy(self):
        for loader in ('file', 'legacy', 'invalid'):
            with self.subTest(loader=loader), tempfile.TemporaryDirectory() as tmp:
                stage=Path(tmp); pseudo=stage/'pseudo';pseudo.write_text('boot-id')
                (stage/'plan.json').write_text(json.dumps(dict(loader=loader,boot_id='boot-id',options='panic=0',initrd=False)))
                def paths(name):
                    return pseudo if str(name).startswith('/proc/') else Path(name)
                with patch.object(cli,'Path',side_effect=paths), patch.object(device,'run',side_effect=RuntimeError('load failed')) as run:
                    if loader == 'invalid':
                        with self.assertRaises(ValueError): cli.load(stage)
                        run.assert_not_called()
                    else:
                        with self.assertRaises(RuntimeError): cli.load(stage)
                        self.assertEqual(run.call_count,1)  # No silent legacy retry.
                        args=run.call_args.args
                        self.assertEqual(args[1], '-s' if loader=='file' else '-c')
                        self.assertEqual(any(a.startswith('--dtb=') for a in args),loader=='legacy')

    def test_host_stage_selects_explicit_installed_entry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(device,'RUN',Path(tmp)), \
             patch.object(cli.os,'geteuid',return_value=0), patch.object(Path,'resolve',lambda p:p), \
             patch.object(device,'prepare',return_value={}) as prepare, \
             patch.object(sys,'argv',['tool','stage','/var/tmp/orchard-warm.abc','prepare','--entry','orchard-test','--profile','full']):
            cli.main()
            self.assertEqual(prepare.call_args.kwargs,{'entry_name':'orchard-test'})
            self.assertEqual(prepare.call_args.args[-1],'full')

    def test_refresh_failure_does_not_request_a_reset(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(device,'RUN',Path(tmp)),\
             patch.object(cli.os,'geteuid',return_value=0),patch.object(cli,'prepare_installed',side_effect=ValueError('bad DT')),\
             patch.object(device,'run') as run,patch.object(sys,'argv',['tool','refresh']):
            with self.assertRaises(ValueError):cli.main()
            run.assert_not_called()
            self.assertFalse((Path(tmp)/'restart-ready').exists())

    def test_dispatch_without_ready_image_halts_without_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';run.mkdir()
            (root/'loaded').write_text('0');(root/'boot').write_text('test-boot');(root/'kmsg').touch()
            def path(name):
                return {'/sys/kernel/kexec_loaded':root/'loaded','/proc/sys/kernel/random/boot_id':root/'boot',
                        '/dev/kmsg':root/'kmsg'}.get(str(name),Path(name))
            with patch.object(device,'RUN',run),patch.object(cli,'Path',side_effect=path),\
                 patch.object(cli.os,'geteuid',return_value=0),patch.object(device,'run') as cmd,\
                 patch.object(sys,'argv',['tool','dispatch']):
                cli.main()
                cmd.assert_called_once_with('systemctl','--force','halt')
                self.assertIn('No hardware reset',(root/'kmsg').read_text())

    def test_load_arms_dispatch_without_a_refresh_unit(self):
        # Device regression 2026-11-08: load wrote only developer-loaded, refresh no longer runs
        # in the kexec transaction, so dispatch refused and halted every warm restart.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';stage=root/'stage'
            for p in (run,stage):p.mkdir()
            (root/'loaded').write_text('1');(root/'boot').write_text('boot-a');(root/'kmsg').touch()
            (stage/'plan.json').write_text(json.dumps({'boot_id':'boot-a','loader':'file','options':'root=PARTUUID=x','initrd':False}))
            def path(name):
                return {'/sys/kernel/kexec_loaded':root/'loaded','/proc/sys/kernel/random/boot_id':root/'boot',
                        '/dev/kmsg':root/'kmsg'}.get(str(name),Path(name))
            with patch.object(device,'RUN',run),patch.object(cli,'Path',side_effect=path),\
                 patch.object(cli.os,'geteuid',return_value=0),patch.object(device,'run') as cmd:
                cli.load(stage)
                self.assertEqual((run/'restart-ready').read_text().strip(),'boot-a')
                cmd.reset_mock()
                with patch.object(sys,'argv',['tool','dispatch']):cli.main()
                cmd.assert_called_once_with('systemctl','--force','kexec')

    def test_refresh_keeps_explicit_developer_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'developer-loaded').write_text('boot');(root/'boot').write_text('boot')
            (root/'loaded').write_text('1')
            def path(name):
                return {'/sys/kernel/kexec_loaded':root/'loaded','/proc/sys/kernel/random/boot_id':root/'boot'}.get(str(name),Path(name))
            with patch.object(device,'RUN',root),patch.object(cli,'Path',side_effect=path),\
                 patch.object(cli.os,'geteuid',return_value=0),patch.object(cli,'prepare_installed') as prepare,\
                 patch.object(sys,'argv',['tool','refresh']):
                cli.main();prepare.assert_not_called()
                self.assertEqual((root/'restart-ready').read_text(),'boot')

    def test_netconsole_records_both_macs_and_uses_configfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths={}
            for name,data in [('/sys/kernel/config/netconsole',''),('/proc/sys/kernel/printk','4 4 1 7'),
                              ('/sys/module/kernel/parameters/initcall_debug','N'),
                              ('/sys/module/printk/parameters/ignore_loglevel','N'),
                              ('/proc/sys/kernel/random/boot_id','boot-id'),
                              ('/sys/class/net/usb0/address','02:00:00:00:00:01'),('/dev/kmsg','')]:
                p=root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True)
                if name.endswith('/netconsole'):
                    p.mkdir(); t=p/'orchard-warm'; t.mkdir(); (t/'enabled').write_text('0\n')  # new targets start disabled
                else:p.write_text(data)
                paths[name]=p
            def path(name): return paths.get(name,root/name.lstrip('/'))
            with patch.object(diagnostics,'Path',side_effect=path),patch.object(diagnostics,'run') as run:
                run.side_effect=lambda *a: json.dumps([{'dev':'usb0','prefsrc':'172.16.42.1'}]) if a[0]=='ip' else ''
                result=diagnostics.netconsole('02:00:00:00:00:02',6777)
                target=root/'sys/kernel/config/netconsole/orchard-warm'
                self.assertEqual((target/'enabled').read_text(),'1\n')
                self.assertEqual((target/'remote_mac').read_text(),'02:00:00:00:00:02\n')
                self.assertEqual((target/'local_ip').read_text(),'172.16.42.1\n')
                self.assertEqual(result['usb_mac'],'02:00:00:00:00:01')
                self.assertEqual(paths['/proc/sys/kernel/printk'].read_text(),'8 4 1 7\n')

    def test_netconsole_bad_route_refuses_before_modprobe(self):
        with patch.object(diagnostics,'run',return_value='[{"dev":"wlan0","prefsrc":"192.168.1.2"}]') as run:
            with self.assertRaises(ValueError):diagnostics.netconsole('02:00:00:00:00:02')
            self.assertEqual(run.call_count,1)

    def test_health_rejects_polled_completion_and_late_timeout(self):
        ap=type('Args',(),dict(sudo_max=5,read_max=3))()
        p=dict(done='1',boot_id='boot',dmesg_rc='0',dmesg=[],sudo_rc='0',sudo_ms='1',read_rc='0',read_ms='10',
               irq_before='1: 3 4 nvme0q0',irq_after='1: 4 4 nvme0q0')
        self.assertIsNone(health.judge(p,ap,'boot'))
        p['irq_after']=p['irq_before'];self.assertIn('lost MSI',health.judge(p,ap,'boot'))
        p['irq_after']='1: 4 4 nvme0q0';p['dmesg']=['nvme I/O tag 5 timeout']
        self.assertIn('timeout/recovery',health.judge(p,ap,'boot'))

    def test_systemd_restart_requires_preload_poweroff_is_unchanged(self):
        unit=(ROOT/'system/overlay/usr/lib/systemd/system/orchard-kexec-refresh.service').read_text()
        # Never pulled into the shutdown transaction: needing /boot there conflicts with
        # umount.target and systemd refuses the kexec (device-found 2026-11-07).
        self.assertNotIn('[Install]',unit); self.assertNotIn('RequiredBy=',unit)
        self.assertNotIn('orchard-kexec-refresh',(ROOT/'release/public_root.py').read_text())
        self.assertNotIn('orchard-kexec-refresh',(ROOT/'system/assemble-rootfs').read_text())
        self.assertIn('orchard-kexec-load.service',(ROOT/'system/overlay/usr/bin/orchard-restart').read_text())
        self.assertFalse((ROOT/'system/overlay/usr/lib/systemd/system/systemd-poweroff.service.d').exists())
        for name in ('systemd-kexec.service','systemd-reboot.service'):
            conf=(ROOT/'system/overlay/usr/lib/systemd/system'/(name+'.d')/'50-orchard-warm.conf').read_text()
            self.assertIn('orchard-kexec dispatch',conf)
            # GPU handover before the jump, on the menu Restart (reboot) path too (device 2026-11-08).
            self.assertIn('ExecStartPre=-/usr/lib/orchard-kexec/quiesce-gpu',conf)
        quiesce=ROOT/'system/overlay/usr/lib/orchard-kexec/quiesce-gpu'
        self.assertTrue(os.access(quiesce,os.X_OK)); self.assertIn('td-kexec',quiesce.read_text())

if __name__=='__main__':unittest.main()
