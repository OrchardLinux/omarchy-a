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

WARM_SUPPORTED = cli.warm_supported  # the real probe, before setUp replaces it

class WarmRestart(unittest.TestCase):
    def setUp(self):
        # The state-machine fixtures model a system with the warm restart
        # mechanisms; the probe is checked separately and defaults to reboot.
        gate = patch.object(cli, 'warm_supported', return_value=True)
        gate.start()
        self.addCleanup(gate.stop)

    def test_warm_support_comes_from_kexec_and_the_reset_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def path(name): return root / str(name).lstrip('/')
            loaded = path('/sys/kernel/kexec_loaded')
            loaded.parent.mkdir(parents=True); loaded.write_text('0\n')
            mode = path('/sys/kernel/reboot/mode'); mode.parent.mkdir(parents=True); mode.write_text('cold\n')
            node = path('/proc/device-tree/soc/watchdog@123'); node.mkdir(parents=True)
            (node/'compatible').write_bytes(b'apple,s8000-wdt\0apple,wdt\0')
            (node/'apple,tethered-boot').touch()
            with patch.object(cli, 'Path', side_effect=path), patch.object(cli.reset, 'Path', side_effect=path), \
                 patch.object(cli.shutil, 'which', return_value='/usr/bin/kexec') as which:
                self.assertTrue(self.real_warm_supported())
                which.assert_called_with('kexec')
                which.return_value = None
                self.assertFalse(self.real_warm_supported())
                which.return_value = '/usr/bin/kexec'
                (node/'apple,tethered-boot').unlink()  # no guard: J71b and every other board today
                self.assertFalse(self.real_warm_supported())
                (node/'apple,tethered-boot').touch(); loaded.unlink()  # no kexec in the kernel
                self.assertFalse(self.real_warm_supported())
                loaded.write_text('0\n')
                self.assertTrue(self.real_warm_supported())
            source = (LIB/'cli.py').read_text() + (ROOT/'system/overlay/usr/bin/orchard-restart').read_text()
            self.assertNotIn('device-feature', source)

    def real_warm_supported(self):
        return WARM_SUPPORTED()

    def test_supported_action_reports_the_probe_as_exit_status(self):
        for answer, code in ((True, 0), (False, 1)):
            with patch.object(cli, 'warm_supported', return_value=answer), \
                 patch.object(sys, 'argv', ['tool', 'supported']), patch.object(device, 'run') as command:
                with self.assertRaises(SystemExit) as exit:
                    cli.main()
                self.assertEqual(exit.exception.code, code)
                command.assert_not_called()
        script = (ROOT/'system/overlay/usr/bin/orchard-restart').read_text()
        self.assertIn('/usr/bin/orchard-kexec supported || exec systemctl reboot', script)

    def test_unqualified_restart_uses_normal_reboot(self):
        with patch.object(cli, 'warm_supported', return_value=False), \
             patch.object(sys, 'argv', ['tool', 'reboot']), patch.object(device, 'run') as command, \
             patch.object(cli, 'prepare_installed') as prepare:
            cli.main()
            command.assert_called_once_with('systemctl', 'reboot')
            prepare.assert_not_called()

    def test_reset_guard_new_old_and_missing(self):
        import reset
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def path(name): return root / str(name).lstrip('/')
            with patch.object(reset, 'Path', side_effect=path):
                mode = path('/sys/kernel/reboot/mode')
                mode.parent.mkdir(parents=True); mode.write_text('cold\n')
                with self.assertRaises(ValueError): reset.backend()
                node = path('/proc/device-tree/soc/watchdog@123')
                node.mkdir(parents=True)
                (node/'compatible').write_bytes(b'apple,s8000-wdt\0apple,wdt\0')
                (node/'apple,tethered-boot').touch()
                self.assertEqual(reset.select(), 'reboot-mode=warm')
                self.assertEqual(reset.select(False), 'reboot-mode=cold')
                (node/'apple,tethered-boot').unlink()
                old = path('/sys/module/apple_wdt/parameters/cold_restart')
                old.parent.mkdir(parents=True); old.write_text('Y\n')
                self.assertEqual(reset.select(), 'cold_restart=N')
                self.assertEqual(reset.select(False), 'cold_restart=Y')

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
            self.assertEqual(run.call_args_list, [unittest.mock.call('kexec', '-u')]*2)
            self.assertFalse((Path(tmp)/'restart-ready').exists())

    def test_dispatch_gpu_failure_uses_ios_escape_without_kexec_or_halt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'gpu-quiesce-failed').write_text('failed')
            (root/'kmsg').touch()
            def path(name):
                return root/'kmsg' if str(name) == '/dev/kmsg' else Path(name)
            events = []
            with patch.object(device, 'RUN', root), patch.object(cli, 'Path', side_effect=path), \
                 patch.object(cli.os, 'geteuid', return_value=0), \
                 patch.object(cli.reset, 'select', side_effect=lambda **kw: events.append(('select', kw))), \
                 patch.object(device, 'run', side_effect=lambda *args: events.append(args)), \
                 patch.object(device, 'guard_outgoing') as guard, \
                 patch.object(sys, 'argv', ['tool', 'dispatch']):
                cli.main()
            self.assertEqual(events, [('select', {'warm': False}),
                                      ('kexec', '-u'), ('systemctl', '--force', 'reboot')])
            guard.assert_not_called()
            self.assertIn('<0>Warm restart aborted', (root/'kmsg').read_text())
            self.assertIn('GPU td-kexec', (root/'kmsg').read_text())

    def test_ios_uses_the_same_cold_escape(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(device, 'RUN', Path(tmp)), \
             patch.object(cli.os, 'geteuid', return_value=0), patch.object(cli, 'cold_reset') as cold, \
             patch.object(sys, 'argv', ['tool', 'ios']):
            cli.main()
            cold.assert_called_once_with()

    def test_quiesce_receipt_retained_on_sysfs_failure_cleared_on_success(self):
        script = (LIB/'quiesce-gpu').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = root/'gpu/command'; command.parent.mkdir()
            command.mkdir()  # Opening a directory for output fails on every host.
            self.assertNotIn('device-feature', script)
            rewritten = script.replace('/run/orchard-kexec', str(root/'run')) \
                .replace('/sys/bus/platform/drivers/apple-g5p-drm/*/command', str(command)) \
                .replace('/dev/kmsg', str(root/'kmsg'))
            result = subprocess.run(['sh', '-c', rewritten], capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((root/'run/gpu-quiesce-failed').exists())
            command.rmdir(); command.touch()
            result = subprocess.run(['sh', '-c', rewritten], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root/'run/gpu-quiesce-failed').exists())
            self.assertEqual(command.read_text(), 'td-kexec\n')

    def test_quiesce_without_a_gpu_handover_command_arms_nothing(self):
        script = (LIB/'quiesce-gpu').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rewritten = script.replace('/run/orchard-kexec', str(root/'run')) \
                .replace('/sys/bus/platform/drivers/apple-g5p-drm', str(root/'no-g5p')) \
                .replace('/dev/kmsg', str(root/'kmsg'))
            result = subprocess.run(['sh', '-c', rewritten], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root/'run').exists())

    def test_dispatch_without_ready_image_uses_cold_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';run.mkdir()
            (root/'loaded').write_text('0');(root/'boot').write_text('test-boot');(root/'kmsg').touch()
            def path(name):
                return {'/sys/kernel/kexec_loaded':root/'loaded','/proc/sys/kernel/random/boot_id':root/'boot',
                        '/dev/kmsg':root/'kmsg'}.get(str(name),Path(name))
            with patch.object(device,'RUN',run),patch.object(cli,'Path',side_effect=path),\
                 patch.object(cli.os,'geteuid',return_value=0),patch.object(device,'run') as cmd,\
                 patch.object(sys,'argv',['tool','dispatch']),\
                 patch.object(cli,'cold_reset',return_value=True) as cold:
                cli.main()
                cmd.assert_not_called()
                self.assertIn('warm dispatch refused',cold.call_args.args[0])

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
                with patch.object(sys,'argv',['tool','dispatch']), patch.object(device,'guard_outgoing'):cli.main()
                cmd.assert_called_once_with('systemctl','--force','kexec')

    def test_refresh_replaces_developer_target_with_current_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'developer-loaded').write_text('boot');(root/'boot').write_text('boot')
            (root/'loaded').write_text('1')
            def path(name):
                return {'/sys/kernel/kexec_loaded':root/'loaded','/proc/sys/kernel/random/boot_id':root/'boot'}.get(str(name),Path(name))
            with patch.object(device,'RUN',root),patch.object(cli,'Path',side_effect=path),\
                 patch.object(cli.os,'geteuid',return_value=0),patch.object(cli,'prepare_installed') as prepare, patch.object(device, 'run') as run,\
                 patch.object(sys,'argv',['tool','refresh']):
                cli.main()
                run.assert_called_once_with('kexec', '-u')
                prepare.assert_called_once_with('default')
                self.assertFalse((root/'developer-loaded').exists())
                self.assertFalse((root/'restart-ready').exists())

    def test_select_unloads_before_changing_default_and_reload(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); boot=root/'boot'; run=root/'run'; run.mkdir()
                entries=boot/'loader/entries'; entries.mkdir(parents=True)
                (entries/'new.conf').write_text('linux /new\n')
                loader=boot/'loader/loader.conf'; loader.write_text('timeout 5\ndefault old.conf\n')
                for name in ('restart-ready', 'developer-loaded', 'loaded.json'):
                    (run/name).write_text('stale')
                def unload(*args):
                    self.assertEqual(args, ('kexec', '-u'))
                    self.assertFalse((run/'restart-ready').exists())
                def prepare(entry):
                    self.assertEqual(entry, 'default')
                    self.assertEqual(loader.read_text(), 'timeout 5\ndefault new.conf\n')
                    self.assertFalse((run/'loaded.json').exists())
                    if fail: raise ValueError('bad image')
                    return {}
                with patch.object(device, 'BOOT', boot), patch.object(device, 'RUN', run), \
                     patch.object(device, 'run', side_effect=unload) as command, \
                     patch.object(cli, 'prepare_installed', side_effect=prepare):
                    if fail:
                        with self.assertRaises(ValueError): cli.select_default('new')
                    else:
                        cli.select_default('new')
                    self.assertEqual(command.call_count, 2 if fail else 1)

    def test_plain_reboot_preparation_never_dispatches_or_halts(self):
        for loaded in ('0', '1'):
            with self.subTest(loaded=loaded), tempfile.TemporaryDirectory() as tmp:
                node=Path(tmp)/'loaded'; node.write_text(loaded)
                with patch.object(cli, 'Path', return_value=node), \
                     patch.object(cli.reset, 'backend'), patch.object(cli.reset, 'select') as select, \
                     patch.object(device, 'run') as run, \
                     patch.object(sys, 'argv', ['tool', 'prepare-reboot']):
                    cli.main()
                    select.assert_called_once_with(warm=False)
                    run.assert_not_called()

    def test_plain_reboot_retains_native_exec_and_bounded_best_effort_handover(self):
        conf=(ROOT/'system/overlay/usr/lib/systemd/system/systemd-reboot.service.d/50-orchard-cold.conf').read_text()
        self.assertNotIn('ExecStart=', conf)
        self.assertNotIn('dispatch', '\n'.join(l for l in conf.splitlines() if not l.startswith('#')))
        self.assertIn('ExecStartPre=-/usr/bin/timeout --kill-after=1 10 ', conf)
        self.assertIn('quiesce-gpu', conf)
        self.assertIn('prepare-reboot', conf)
        watch=(ROOT/'system/overlay/usr/lib/systemd/system/orchard-kexec-refresh.path').read_text()
        self.assertIn('PathChanged=/boot/loader/loader.conf', watch)
        self.assertIn('PathChanged=/boot/loader/entries', watch)
        self.assertIn('WantedBy=multi-user.target', watch)

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
        self.assertIn('orchard-kexec-refresh.path',(ROOT/'release/public_root.py').read_text())
        self.assertNotIn('orchard-kexec-refresh',(ROOT/'system/assemble-rootfs').read_text())
        self.assertIn('orchard-kexec-load.service',(ROOT/'system/overlay/usr/bin/orchard-restart').read_text())
        self.assertFalse((ROOT/'system/overlay/usr/lib/systemd/system/systemd-poweroff.service.d').exists())
        for name in ('systemd-kexec.service',):
            conf=(ROOT/'system/overlay/usr/lib/systemd/system'/(name+'.d')/'50-orchard-warm.conf').read_text()
            self.assertIn('orchard-kexec dispatch',conf)
            # GPU handover before the jump, on the menu Restart (reboot) path too (device 2026-11-08).
            self.assertIn('ExecStartPre=-/usr/bin/timeout --kill-after=1 10 /usr/lib/orchard-kexec/quiesce-gpu',conf)
        quiesce=ROOT/'system/overlay/usr/lib/orchard-kexec/quiesce-gpu'
        self.assertTrue(os.access(quiesce,os.X_OK)); self.assertIn('td-kexec',quiesce.read_text())

    def test_cold_escape_continues_after_select_or_unload_failure(self):
        for failure in ('select', 'unload'):
            with self.subTest(failure=failure), patch.object(cli.reset, 'select',
                    side_effect=ValueError('bad guard') if failure=='select' else None), \
                 patch.object(cli, 'unload', side_effect=OSError('busy') if failure=='unload' else None), \
                 patch.object(device, 'run') as run, patch.object(cli, 'Path') as paths:
                paths.return_value.read_text.return_value='cold\n'
                self.assertTrue(cli.cold_reset('test'))
                run.assert_called_once_with('systemctl', '--force', 'reboot')

    def test_cold_escape_timeout_tries_sysrq_and_reports_failure_if_it_returns(self):
        with patch.object(cli.reset, 'select', side_effect=OSError('missing')), \
             patch.object(cli, 'unload', side_effect=subprocess.TimeoutExpired('kexec',60)), \
             patch.object(device, 'run', side_effect=subprocess.TimeoutExpired('systemctl',60)), \
             patch.object(cli, 'Path') as paths:
            paths.return_value.read_text.return_value='cold\n'
            self.assertFalse(cli.cold_reset())
            self.assertIn(unittest.mock.call('/proc/sysrq-trigger'), paths.call_args_list)
            self.assertIn(unittest.mock.call('/sys/kernel/reboot/mode'), paths.call_args_list)
            paths.return_value.write_text.assert_any_call('b')

    def test_cold_escape_all_io_failures_return_without_exception(self):
        with patch.object(cli.reset, 'select', side_effect=ValueError('missing')), \
             patch.object(cli, 'unload', side_effect=OSError('unload')), \
             patch.object(device, 'run', side_effect=OSError('reboot')), \
             patch.object(cli, 'Path') as paths:
            paths.return_value.write_text.side_effect=OSError('I/O')
            self.assertFalse(cli.cold_reset('test'))

    def test_failed_receipt_precedes_dispatch_lock(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(device,'RUN',Path(tmp)), \
             patch.object(cli.os,'geteuid',return_value=0), \
             patch.object(cli.fcntl,'flock',side_effect=BlockingIOError) as flock, \
             patch.object(cli,'cold_reset',return_value=True) as cold, \
             patch.object(sys,'argv',['tool','dispatch']):
            (Path(tmp)/'gpu-quiesce-failed').touch()
            cli.main()
            flock.assert_not_called()
            cold.assert_called_once()

    def test_dispatch_lock_failure_escapes_and_failed_escape_fails_unit(self):
        for result in (True,False):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp, \
                 patch.object(device,'RUN',Path(tmp)),patch.object(cli.os,'geteuid',return_value=0), \
                 patch.object(cli.fcntl,'flock',side_effect=BlockingIOError), \
                 patch.object(cli,'cold_reset',return_value=result) as cold, \
                 patch.object(sys,'argv',['tool','dispatch']):
                if result:
                    cli.main()
                else:
                    with self.assertRaises(SystemExit) as status:cli.main()
                    self.assertEqual(status.exception.code,1)
                cold.assert_called_once()
        conf=(ROOT/'system/overlay/usr/lib/systemd/system/systemd-kexec.service.d/50-orchard-warm.conf').read_text()
        self.assertIn('[Unit]\n',conf)
        self.assertIn('FailureAction=none',conf.split('[Service]')[0])
        self.assertIn('SuccessAction=none',conf.split('[Service]')[0])


    def test_failed_guard_selects_cold_before_requesting_reboot(self):
        events=[]
        with tempfile.TemporaryDirectory() as tmp:
            mode=Path(tmp)/'mode';mode.write_text('warm\n')
            def path(name):
                return mode if str(name)=='/sys/kernel/reboot/mode' else Path(tmp)/'kmsg'
            def reboot(*args):
                self.assertEqual(mode.read_text(),'cold\n');events.append(args)
            with patch.object(cli.reset,'select',side_effect=ValueError('guard')), \
                 patch.object(cli,'Path',side_effect=path),patch.object(cli,'unload'), \
                 patch.object(device,'run',side_effect=reboot):
                self.assertTrue(cli.cold_reset())
            self.assertEqual(events,[('systemctl','--force','reboot')])

    def test_unselectable_cold_arms_native_watchdog_without_warm_reboot(self):
        def path(name):
            obj=unittest.mock.Mock()
            if str(name).endswith('/identity'):obj.read_text.return_value='Apple SoC Watchdog'
            elif str(name).endswith('/mode'):obj.write_text.side_effect=OSError('mode unavailable')
            return obj
        with patch.object(cli.reset,'select',side_effect=OSError('guard')), \
             patch.object(cli,'Path',side_effect=path),patch.object(cli.os,'open',return_value=9), \
             patch.object(cli.os,'write') as write,patch.object(cli.os,'close'), \
             patch.object(cli.fcntl,'ioctl') as ioctl,patch.object(device,'run') as reboot:
            self.assertTrue(cli.cold_reset())
            reboot.assert_not_called();write.assert_called_once_with(9,b'\0')
            self.assertEqual(ioctl.call_args.args[:2],(9,0xc0045706))


    def test_unqualified_dispatch_escapes_without_enqueuing_reboot(self):
        with patch.object(cli,'warm_supported',return_value=False), \
             patch.object(sys,'argv',['tool','dispatch']), \
             patch.object(cli,'cold_reset',return_value=True) as cold, \
             patch.object(device,'run') as command:
            cli.main()
            cold.assert_called_once();command.assert_not_called()
