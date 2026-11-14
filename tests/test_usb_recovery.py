#!/usr/bin/env python3
"""Test the installed watchdog against temporary files; never touch a UDC."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / 'system/overlay/usr/libexec/omarchy-usb-recover'
loader = importlib.machinery.SourceFileLoader('usb_recover', str(PROGRAM))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sysfs = Path(self.temp.name)
        self.messages, self.disconnects = [], []
        self.gadget = self.sysfs / 'kernel/config/usb_gadget/g1'
        self.udc = self.gadget / 'UDC'
        self.put('class/power_supply/usb/online', '1')
        self.put('class/power_supply/usb/current_max', '500000')
        self.put('class/net/usb0/flags', '0x1003')
        self.put('class/net/usb0/carrier', '1')
        self.put('class/udc/20c100000.usbdev/state', 'configured')
        self.put('kernel/config/usb_gadget/g1/UDC', '20c100000.usbdev')
        self.put('kernel/config/usb_gadget/g1/functions/ecm.usb0/ifname', 'usb0')
        config = self.gadget / 'configs/c.1'
        config.mkdir(parents=True)
        (config / 'ecm.usb0').symlink_to(self.gadget / 'functions/ecm.usb0')
        self.recovery = module.Recovery(self.sysfs, self.pause, self.log, probe=lambda: False,
                                        link=lambda state: self.fail("unexpected link bounce"),
                                        kmsg=lambda message: self.fail("unexpected kmsg"))
        self.recovery.step(0)  # Observe the working link before a loss.

    def put(self, path, value):
        target = self.sysfs / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def log(self, message, **kwargs):
        self.messages.append(message)

    def pause(self, delay):
        self.assertEqual(delay, 0.2)
        self.assertEqual(self.udc.read_text(), '\n')
        self.disconnects.append(delay)

    def lose(self, start=1, end=11):
        self.put('class/net/usb0/carrier', '0')
        self.recovery.step(start)
        self.recovery.step(end)

    def assert_bound(self):
        self.assertEqual(self.udc.read_text().strip(), '20c100000.usbdev')

    def test_debounce_and_rebind(self):
        self.lose(end=10.9)
        self.assertEqual(self.disconnects, [])
        self.recovery.step(11)
        self.assertEqual(len(self.disconnects), 1)
        self.assert_bound()
        self.assertIn('VBUS present', self.messages[0])

    def test_healthy_and_never_enumerated(self):
        for now in (100, 200, 300):
            self.recovery.step(now)
        self.recovery.seen_carrier = False
        self.lose()
        self.assertEqual(self.disconnects, [])

    def test_short_loss_resets_timer(self):
        self.lose(end=5)
        self.put('class/net/usb0/carrier', '1')
        self.recovery.step(6)
        self.lose(7, 16)
        self.assertEqual(self.disconnects, [])
        self.recovery.step(17)
        self.assertEqual(len(self.disconnects), 1)

    def test_absent_unknown_and_suspended_source(self):
        for prop, value in (('online', '0'), ('online', ''), ('current_max', '0'),
                            ('current_max', ''), ('current_max', '-5')):
            with self.subTest(prop=prop, value=value):
                self.setUp_source()
                self.put('class/power_supply/usb/' + prop, value)
                self.lose(1, 100)
                self.assertEqual(self.disconnects, [])

    def setUp_source(self):
        self.put('class/power_supply/usb/online', '1')
        self.put('class/power_supply/usb/current_max', '500000')
        self.recovery.seen_carrier = True
        self.recovery.lost_at = None

    def test_admin_down_and_udc_not_configured(self):
        self.put('class/net/usb0/flags', '0x1002')
        self.lose()
        self.put('class/net/usb0/flags', '0x1003')
        for state in ('suspended', 'not attached', 'addressed', ''):
            self.put('class/udc/20c100000.usbdev/state', state)
            self.lose(20, 40)
        self.assertEqual(self.disconnects, [])

    def test_no_binding_and_inactive_function(self):
        self.udc.write_text('')
        self.lose()
        self.assertEqual(self.udc.read_text(), '')
        self.udc.write_text('20c100000.usbdev')
        (self.gadget / 'configs/c.1/ecm.usb0').unlink()
        self.lose(20, 40)
        self.assertEqual(self.disconnects, [])

    def test_other_interface_and_ambiguous_gadgets(self):
        self.put('kernel/config/usb_gadget/g1/functions/ecm.usb0/ifname', 'usb1')
        self.lose()
        self.put('kernel/config/usb_gadget/g1/functions/ecm.usb0/ifname', 'usb0')
        second = self.gadget.with_name('g2')
        self.put('kernel/config/usb_gadget/g2/UDC', 'other.udc')
        self.put('kernel/config/usb_gadget/g2/functions/ecm.usb0/ifname', 'usb0')
        (second / 'configs/c.1').mkdir(parents=True)
        (second / 'configs/c.1/ecm.usb0').symlink_to(second / 'functions/ecm.usb0')
        self.lose(20, 40)
        self.assertEqual(self.disconnects, [])
        self.assertEqual((second / 'UDC').read_text(), 'other.udc')

    def test_cooldown_and_attempt_limit(self):
        self.lose()
        for now in range(12, 70):
            self.recovery.step(now)
        self.assertEqual(len(self.disconnects), 1)
        self.recovery.step(71)
        self.recovery.step(72)
        self.recovery.step(131)
        self.recovery.step(132)
        self.recovery.step(1000)
        self.assertEqual(len(self.disconnects), 3)
        self.assert_bound()
        self.put('class/power_supply/usb/online', '0')
        self.recovery.step(1001)
        self.assertEqual(self.recovery.attempts, 0)
        self.assertFalse(self.recovery.seen_carrier)

    def test_vbus_loss_disarms_even_with_stale_carrier(self):
        self.put('class/power_supply/usb/online', '0')
        self.recovery.step(1)
        self.assertFalse(self.recovery.seen_carrier)
        self.put('class/power_supply/usb/online', '1')
        self.lose(2, 30)
        self.assertEqual(self.disconnects, [])

    def test_stop_or_error_during_disconnect_restores_binding(self):
        def interrupted(delay):
            self.pause(delay)
            raise OSError('interrupted')
        self.recovery.pause = interrupted
        self.lose()
        self.assert_bound()
        self.assertIn('rebind failed', self.messages[-1])

    def test_other_owner_during_disconnect_is_preserved(self):
        def other_owner(delay):
            self.pause(delay)
            self.udc.write_text('other.udc')
        self.recovery.pause = other_owner
        self.lose()
        self.assertEqual(self.udc.read_text(), 'other.udc')

    def peer_watchdog(self, ncm=True):
        if ncm:
            old = self.gadget/'functions/ecm.usb0'
            old.rename(self.gadget/'functions/ncm.usb0')
            (self.gadget/'configs/c.1/ecm.usb0').unlink()
            (self.gadget/'configs/c.1/ncm.usb0').symlink_to(self.gadget/'functions/ncm.usb0')
        self.reachable = True
        self.links, self.kmsgs = [], []
        self.recovery = module.Recovery(self.sysfs, self.pause, self.log,
            probe=lambda: self.reachable, link=self.links.append, kmsg=self.kmsgs.append)
        self.recovery.step(0)

    def test_ncm_carrier_up_peer_timeout_bounces_only_netdev_and_logs_counter(self):
        self.peer_watchdog()
        self.put('class/power_supply/usb/current_max', '0')
        self.reachable = False
        self.recovery.step(1); self.recovery.step(15.9)
        self.assertEqual(self.links, [])
        self.recovery.step(16)
        self.assertEqual(self.links, ['down', 'up'])
        self.assert_bound()
        self.assertEqual(self.disconnects, [])
        self.assertEqual(len(self.kmsgs), 1)
        self.assertIn('usb0-stall-bounce', self.kmsgs[0])
        self.assertIn('tx_dropped=', self.kmsgs[0])

    def test_ecm_peer_recovery_and_timeout_reset_on_reply(self):
        self.peer_watchdog(ncm=False)
        self.reachable = False; self.recovery.step(1)
        self.reachable = True; self.recovery.step(10)
        self.reachable = False; self.recovery.step(11); self.recovery.step(25)
        self.assertEqual(self.links, [])
        self.recovery.step(26)
        self.assertEqual(self.links, ['down', 'up'])

    def test_never_reachable_sleep_unconfigured_and_vbus_loss_do_not_bounce(self):
        self.peer_watchdog()
        self.recovery.seen_peer = False
        self.reachable = False
        self.recovery.step(1); self.recovery.step(40)
        self.assertEqual(self.links, [])
        self.reachable = True; self.recovery.step(41); self.reachable = False
        self.put('class/udc/20c100000.usbdev/state', 'suspended')
        self.recovery.step(42); self.recovery.step(100)
        self.assertEqual(self.links, [])
        self.assertFalse(self.recovery.seen_peer)
        self.put('class/udc/20c100000.usbdev/state', 'configured')
        self.reachable = True; self.recovery.step(101); self.reachable = False
        self.put('class/power_supply/usb/online', '0')
        self.recovery.step(102); self.recovery.step(200)
        self.assertEqual(self.links, [])
        self.assertFalse(self.recovery.seen_peer)

    def test_peer_bounces_have_cooldown_and_three_attempt_cap_until_reply(self):
        self.peer_watchdog(); self.reachable = False
        for now in range(1, 300): self.recovery.step(now)
        self.assertEqual(self.links, ['down', 'up'] * 3)
        self.reachable = True; self.recovery.step(300)
        self.reachable = False; self.recovery.step(301); self.recovery.step(316)
        self.assertEqual(self.links, ['down', 'up'] * 4)

    def test_failed_down_restores_up_and_never_rebinds(self):
        self.peer_watchdog(); self.reachable = False
        def link(state):
            self.links.append(state)
            if state == 'down': raise subprocess.TimeoutExpired('ip', 2)
        self.recovery.link = link
        self.recovery.step(1); self.recovery.step(16)
        self.assertEqual(self.links, ['down', 'up'])
        self.assert_bound()
        self.assertIn('bounce failed', self.messages[-1])

    def test_recovery_commands_are_explicit_system_dependencies(self):
        packages = (ROOT/'system/packages.txt').read_text().splitlines()
        self.assertIn('iputils', packages)
        self.assertIn('iproute2', packages)
        unit = (ROOT/'system/overlay/usr/lib/systemd/system/omarchy-usb-recover.service').read_text()
        self.assertIn('TimeoutStopSec=10', unit)

    def test_probe_is_interface_scoped_and_bounded(self):
        with patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([],0)) as run:
            self.assertTrue(module.peer_reachable())
            args, kw = run.call_args
            self.assertEqual(args[0], ['ping','-n','-I','usb0','-c','1','-W','1','-w','2','172.16.42.2'])
            self.assertEqual(kw['timeout'], 3)
        with patch.object(module.subprocess,'run',side_effect=subprocess.TimeoutExpired('ping',3)):
            self.assertFalse(module.peer_reachable())



if __name__ == '__main__':
    unittest.main()
