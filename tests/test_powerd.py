"""omarchy-powerd: the state machine (docs/power-and-lock.md) and its parsing."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import os
import pwd
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock
from unittest.mock import patch
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
PATH = PROJECT / 'system/overlay/usr/libexec/omarchy-powerd'
loader = importlib.machinery.SourceFileLoader('omarchy_powerd', str(PATH))
spec = importlib.util.spec_from_loader(loader.name, loader)
powerd = importlib.util.module_from_spec(spec)
loader.exec_module(powerd)
Machine, EVENTS = powerd.Machine, powerd.EVENTS
ON, SETTLING, DARK, SUSPENDING = powerd.ON, powerd.SETTLING, powerd.DARK, powerd.SUSPENDING


def run(machine, *events):
    actions = []
    for event in events:
        actions = machine.handle(event)
    return actions


def asleep():
    machine = Machine()
    run(machine, 'power', 'lock-ok', 'settle')
    return machine


class SupplyEvents(unittest.TestCase):
    def test_a_supplys_online_state_is_read_from_its_uevent(self):
        message = b'change@/devices/x/power_supply/lightning\0ACTION=change\0SUBSYSTEM=power_supply\0' \
                  b'POWER_SUPPLY_NAME=lightning\0POWER_SUPPLY_ONLINE=1\0'
        self.assertEqual(powerd.parse_supply_uevent(message), ('lightning', True))
        self.assertEqual(powerd.parse_supply_uevent(message.replace(b'ONLINE=1', b'ONLINE=0')), ('lightning', False))

    def test_other_uevents_are_ignored(self):
        self.assertIsNone(powerd.parse_supply_uevent(b'change@/x\0SUBSYSTEM=input\0POWER_SUPPLY_ONLINE=1\0'))
        self.assertIsNone(powerd.parse_supply_uevent(b'change@/x\0SUBSYSTEM=power_supply\0POWER_SUPPLY_NAME=battery\0'))

    def test_only_being_plugged_in_counts(self):
        known = {}
        self.assertTrue(powerd.plugged_in(known, 'lightning', True))
        self.assertFalse(powerd.plugged_in(known, 'lightning', True))
        self.assertFalse(powerd.plugged_in(known, 'lightning', False))
        self.assertTrue(powerd.plugged_in(known, 'lightning', True))


class Scenarios(unittest.TestCase):
    def test_power_darkens_at_once_and_sleeps_after_the_settle_time(self):
        machine = Machine()
        self.assertEqual(machine.handle('power'), ['dark', 'lock', 'arm-settle'])
        self.assertEqual(machine.state, SETTLING)
        self.assertEqual(machine.handle('lock-ok'), [])
        self.assertEqual(machine.handle('settle'), ['suspend'])
        self.assertEqual(machine.state, SUSPENDING)

    def test_the_first_press_wakes(self):
        machine = asleep()
        self.assertEqual(machine.handle('power'), ['cancel-suspend', 'light', 'woke'])
        self.assertEqual(machine.state, ON)

    def test_home_wakes_too_but_never_darkens(self):
        machine = asleep()
        self.assertIn('light', machine.handle('home'))
        machine.handle('sleep-ended')
        self.assertEqual(machine.handle('home'), [])
        self.assertEqual(machine.state, ON)

    def test_a_press_after_the_panel_lit_is_a_command_even_while_the_sleep_finishes(self):
        machine = asleep()
        machine.handle('power')
        self.assertEqual(machine.handle('power'), ['dark', 'lock', 'arm-settle'])
        run(machine, 'lock-ok')
        # No second suspend on top of the one still finishing; it follows.
        self.assertEqual(machine.handle('settle'), [])
        self.assertEqual(machine.state, SETTLING)
        self.assertEqual(machine.handle('sleep-ended'), ['take-inhibitor', 'suspend'])
        self.assertEqual(machine.state, SUSPENDING)

    def test_quick_presses_while_awake_just_toggle_the_screen(self):
        machine = Machine()
        for _ in range(5):
            self.assertIn('dark', machine.handle('power'))
            self.assertEqual(machine.state, SETTLING)
            self.assertEqual(machine.handle('power'), ['cancel-settle', 'light', 'woke'])
            self.assertEqual(machine.state, ON)

    def test_no_sleep_before_the_lock_is_confirmed(self):
        machine = Machine()
        run(machine, 'power', 'settle')
        self.assertEqual(machine.state, SETTLING)
        self.assertEqual(machine.handle('lock-ok'), ['suspend'])

    def test_a_failed_lock_lights_the_screen_and_never_sleeps(self):
        machine = Machine()
        machine.handle('power')
        self.assertEqual(machine.handle('lock-failed'), ['cancel-settle', 'notify', 'light', 'woke'])
        self.assertEqual(machine.state, ON)

    def test_a_wake_without_a_button_stays_dark_and_sleeps_again(self):
        machine = asleep()
        self.assertEqual(machine.handle('sleep-ended'), ['take-inhibitor', 'arm-settle'])
        self.assertEqual(machine.state, SETTLING)
        self.assertEqual(machine.handle('settle'), ['suspend'])

    def test_touch_and_volume_are_not_inputs_of_the_dark_states(self):
        self.assertNotIn('touch', EVENTS)
        self.assertNotIn('volume', EVENTS)

    def test_playback_stays_dark_and_running_then_sleeps_when_it_stops(self):
        machine = Machine()
        run(machine, 'power', 'lock-ok')
        self.assertEqual(machine.handle('playing'), ['cancel-settle'])
        self.assertEqual(machine.state, DARK)
        self.assertEqual(machine.handle('not-playing'), ['arm-settle'])
        self.assertEqual(machine.state, SETTLING)
        self.assertEqual(machine.handle('settle'), ['suspend'])

    def test_a_block_inhibitor_found_at_the_last_moment_is_playback(self):
        machine = asleep()
        machine.handle('suspend-blocked')
        self.assertEqual((machine.state, machine.playing, machine.inflight), (DARK, True, False))
        self.assertEqual(machine.handle('not-playing'), ['arm-settle'])

    def test_a_board_without_suspend_stays_dark_until_pressed(self):
        machine = asleep()
        self.assertEqual(machine.handle('suspend-refused'), ['take-inhibitor'])
        self.assertEqual(machine.state, DARK)
        self.assertEqual(machine.handle('not-playing'), [])
        self.assertEqual(machine.state, DARK)
        self.assertIn('light', machine.handle('power'))

    def test_a_cancelled_suspend_cannot_swallow_presses_for_ever(self):
        machine = asleep()
        machine.handle('power')
        self.assertEqual(machine.handle('timeout'), ['take-inhibitor'])
        self.assertIn('dark', machine.handle('power'))

    def test_a_suspend_that_did_not_happen_is_tried_again(self):
        for event in ('timeout', 'suspend-busy'):
            machine = asleep()
            self.assertEqual(machine.handle(event), ['take-inhibitor', 'arm-settle'])
            self.assertEqual(machine.state, SETTLING)

    def test_the_lock_screens_blank_timeout_leads_to_sleep(self):
        machine = Machine()
        run(machine, 'power', 'lock-ok', 'power', 'sleep-ended')  # back on the lit lock screen
        self.assertEqual(machine.handle('idle'), ['dark', 'arm-grace'])
        # An already locked screen stays locked during the grace interval.
        run(machine, 'grace-ended', 'lock-ok')
        self.assertEqual(machine.handle('settle'), ['suspend'])

    def test_a_suspend_from_elsewhere_locks_and_darkens_before_it_is_let_through(self):
        machine = Machine()
        self.assertEqual(machine.handle('sleep-signal'), ['dark', 'lock'])
        self.assertEqual(machine.state, SUSPENDING)
        self.assertEqual(machine.handle('lock-ok'), ['release-inhibitor'])

    def test_a_suspend_this_daemon_asked_for_needs_nothing_more_from_the_signal(self):
        machine = asleep()
        self.assertEqual(machine.handle('sleep-signal'), [])


class IdleGrace(unittest.TestCase):
    def test_idle_waits_eight_seconds_before_requesting_lock(self):
        machine = Machine()
        self.assertEqual(machine.handle('idle'), ['dark', 'arm-grace'])
        self.assertEqual(machine.state, powerd.GRACE)
        self.assertEqual(machine.handle('settle'), [])
        self.assertEqual(machine.handle('playing'), [])
        self.assertEqual(machine.handle('grace-ended'), ['dark', 'lock', 'arm-settle'])
        self.assertEqual(machine.state, SETTLING)
        self.assertEqual(powerd.IDLE_GRACE_SECONDS, 8.0)

    def test_quick_wake_never_requests_lock_or_suspend(self):
        for event in ('power', 'home', 'wake'):
            machine = Machine()
            machine.handle('idle')
            self.assertEqual(machine.handle(event), ['cancel-grace', 'light', 'woke'])
            self.assertEqual(machine.handle('grace-ended'), [])
            self.assertEqual(machine.state, ON)

    def test_explicit_power_and_external_suspend_bypass_grace(self):
        machine = Machine()
        self.assertIn('lock', machine.handle('power'))
        machine = Machine()
        machine.handle('idle')
        actions = machine.handle('sleep-signal')
        self.assertIn('cancel-grace', actions)
        self.assertIn('lock', actions)
        self.assertNotIn('release-inhibitor', actions)
        self.assertEqual(machine.handle('lock-ok'), ['release-inhibitor'])

    def test_menu_lock_locks_at_once_also_during_grace(self):
        machine = Machine()
        self.assertEqual(machine.handle('lock'), ['dark', 'lock', 'arm-settle'])
        self.assertEqual(machine.state, SETTLING)
        machine = Machine()
        machine.handle('idle')
        self.assertEqual(machine.handle('lock'), ['cancel-grace', 'dark', 'lock', 'arm-settle'])
        self.assertEqual(machine.state, SETTLING)
        # anywhere else it changes nothing: already dark and locked, or asleep
        self.assertEqual(machine.handle('lock'), [])


class Exhaustive(unittest.TestCase):
    """Every input in every reachable state keeps the invariants."""

    def walk(self):
        start = Machine()
        seen, todo = {}, [(start, False)]
        def key(machine, dark):
            return (*sorted(vars(machine).items()), dark)
        seen[key(start, False)] = True
        while todo:
            machine, dark = todo.pop()
            for event in EVENTS:
                after = Machine()
                vars(after).update(vars(machine))
                actions = after.handle(event)
                now_dark = dark
                for action in actions:
                    if action == 'dark':
                        now_dark = True
                    elif action == 'light':
                        now_dark = False
                    elif action == 'suspend':
                        yield 'suspend', event, machine, after, now_dark
                    elif action == 'release-inhibitor':
                        yield 'release', event, machine, after, now_dark
                yield 'state', event, machine, after, now_dark
                if key(after, now_dark) not in seen:
                    seen[key(after, now_dark)] = True
                    todo.append((after, now_dark))

    def test_invariants(self):
        states = set()
        for kind, event, before, after, dark in self.walk():
            context = (event, vars(before), vars(after))
            states.add(after.state)
            if kind == 'state':
                self.assertIn(after.state, powerd.STATES, context)
                # The panel and the state cannot disagree: dark exactly when not ON.
                self.assertEqual(dark, after.state != ON, context)
                if after.state == SUSPENDING:
                    self.assertTrue(after.inflight, context)
                # Dark and running with no timer only for playback or a board that cannot suspend.
                if after.state == DARK:
                    self.assertTrue(after.playing or after.no_suspend, context)
            elif kind == 'suspend':
                # Sleep is only ever asked for dark and locked.
                self.assertTrue(dark, context)
                self.assertTrue(after.lock_ok, context)
                self.assertEqual(after.state, SUSPENDING, context)
                self.assertIn(before.state, (SETTLING,), context)
        self.assertEqual(states, set(powerd.STATES))

    def test_power_and_home_always_light_a_dark_screen(self):
        for kind, event, before, after, dark in self.walk():
            if kind == 'state' and event in ('power', 'home') and before.state != ON:
                self.assertEqual(after.state, ON, (event, vars(before)))

    def test_home_never_darkens(self):
        for kind, event, before, after, dark in self.walk():
            if kind == 'state' and event == 'home':
                self.assertEqual(after.state, ON, vars(before))


class Inhibitor(unittest.TestCase):
    def test_an_inhibitor_logind_refused_is_taken_again_and_a_released_one_is_not(self):
        daemon = powerd.Daemon()
        dead = type('Dead', (), {'poll': lambda self: 1})()
        alive = type('Alive', (), {'poll': lambda self: None, 'terminate': lambda self: None,
                                   'wait': lambda self: 0})()
        with patch.object(powerd.subprocess, 'Popen', side_effect=[dead, alive]) as started:
            daemon.take_inhibitor()
            daemon.keep_inhibitor()
            self.assertEqual(started.call_count, 2)
            daemon.keep_inhibitor()
            self.assertEqual(started.call_count, 2)
            daemon.release_inhibitor()
            daemon.keep_inhibitor()
            self.assertEqual(started.call_count, 2)

    def test_a_logind_that_started_again_gets_asked_only_if_we_hold_one(self):
        daemon = powerd.Daemon()
        alive = type('Alive', (), {'poll': lambda self: None, 'terminate': lambda self: None,
                                   'wait': lambda self: 0})
        with patch.object(powerd.subprocess, 'Popen', side_effect=lambda *_: alive()) as started:
            daemon.renew_inhibitor()
            self.assertEqual(started.call_count, 0)
            daemon.take_inhibitor()
            first = daemon.inhibitor
            daemon.renew_inhibitor()
            self.assertEqual(started.call_count, 2)
            self.assertIsNot(daemon.inhibitor, first)
            self.assertTrue(daemon.want_inhibitor)


class Parsing(unittest.TestCase):
    def test_key_edges_only_power_and_home_presses_and_releases(self):
        event = powerd.INPUT_EVENT.pack
        data = (event(10, 500000, 1, 116, 1) + event(10, 600000, 1, 116, 0) + event(11, 0, 1, 172, 1) +
                event(11, 0, 1, 115, 1) + event(12, 0, 0, 0, 0) + event(13, 0, 1, 116, 2))
        self.assertEqual(powerd.key_edges(data), [('power', True, 10.5), ('power', False, 10.6), ('home', True, 11.0)])
        self.assertEqual(powerd.INPUT_EVENT.size, 24)


class SmartCover(unittest.TestCase):
    def test_cover_edges_only_the_cover_switch(self):
        event = powerd.INPUT_EVENT.pack
        data = (event(5, 0, 5, 0x10, 1) + event(5, 0, 0, 0, 0) + event(6, 500000, 5, 0x10, 0) +
                event(7, 0, 5, 0x00, 1) + event(8, 0, 1, 116, 1))
        self.assertEqual(powerd.cover_edges(data), [(True, 5.0), (False, 6.5)])

    def test_a_device_reports_the_cover_from_its_switch_bitmap(self):
        self.assertTrue(powerd.reports_cover('10000\n'))
        self.assertTrue(powerd.reports_cover('0 10001\n'))
        self.assertFalse(powerd.reports_cover('1\n'))
        self.assertFalse(powerd.reports_cover('0\n'))
        self.assertFalse(powerd.reports_cover(''))

    def test_closing_locks_once_and_opening_wakes_once_across_both_sensors(self):
        cover = powerd.Cover()
        self.assertEqual(cover.change('a', True), 'lock')
        self.assertIsNone(cover.change('b', True))
        self.assertIsNone(cover.change('a', False))
        self.assertEqual(cover.change('b', False), 'wake')
        self.assertIsNone(cover.change('b', False))

    def test_a_lost_sensor_does_not_keep_the_cover_closed(self):
        cover = powerd.Cover()
        cover.change('a', True)
        cover.forget('a')
        self.assertEqual(cover.change('b', True), 'lock')

    def test_closing_darkens_and_locks_and_opening_lights(self):
        machine = powerd.Machine()
        self.assertEqual(machine.handle('lock'), ['dark', 'lock', 'arm-settle'])
        self.assertEqual(machine.handle('wake'), ['cancel-settle', 'light', 'woke'])
        self.assertEqual(machine.state, powerd.ON)


class Buttons(unittest.TestCase):
    def events(self, edges, lit=True):
        buttons = powerd.Buttons()
        return [e for e in (buttons.edge(name, down, when, lit) for name, down, when in edges) if e]

    def test_a_short_press_on_a_lit_screen_darkens_on_release(self):
        buttons = powerd.Buttons()
        self.assertIsNone(buttons.edge('power', True, 1.0, True))
        self.assertEqual(buttons.edge('power', False, 1.2, True), 'power')

    def test_power_with_home_held_does_nothing_for_dfu_and_restart(self):
        for edges in ([('power', True, 1.0), ('home', True, 1.1), ('home', False, 11), ('power', False, 11)],
                      [('home', True, 1.0), ('power', True, 1.1), ('power', False, 3.0), ('home', False, 3.1)],
                      [('power', True, 1.0), ('home', True, 1.1)]):
            with self.subTest(edges=edges):
                self.assertEqual(self.events(edges), ['home'])

    def test_a_short_home_and_power_press_takes_one_screenshot_on_release(self):
        for edges in ([('power', True, 1.0), ('home', True, 1.1), ('power', False, 1.3), ('home', False, 1.4)],
                      [('home', True, 1.0), ('power', True, 1.05), ('home', False, 1.3), ('power', False, 1.35)]):
            with self.subTest(edges=edges):
                self.assertEqual(self.events(edges), ['home', 'screenshot'])

    def test_a_screenshot_press_does_not_count_as_a_home_press(self):
        buttons = powerd.Buttons()
        for name, down, when in (('power', True, 1.0), ('home', True, 1.1), ('home', False, 1.3), ('power', False, 1.4)):
            buttons.edge(name, down, when, True)
        self.assertTrue(buttons.home_in_combo)
        buttons.edge('home', True, 5.0, True)
        self.assertFalse(buttons.home_in_combo)

    def test_user_commands_look_groups_up_in_the_child(self):
        # os.getgrouplist would hold the interpreter lock through nss-systemd,
        # which stalls until systemd has finished a sleep.
        user = pwd.struct_passwd(('tablet', 'x', 1000, 1000, '', '/home/tablet', '/bin/bash'))
        with mock.patch.object(powerd, 'command') as command, \
                mock.patch.object(powerd.os, 'getgrouplist', side_effect=AssertionError('NSS in powerd')):
            powerd.as_user(user, 'omarchy-shell', 'lock', 'woke')
        argv, options = command.call_args
        self.assertEqual(argv[:5], ('setpriv', '--reuid=1000', '--regid=1000', '--init-groups', '--'))
        self.assertEqual(argv[5:], ('omarchy-shell', 'lock', 'woke'))
        self.assertNotIn('extra_groups', options)
        self.assertEqual(options['env']['HOME'], '/home/tablet')

    def test_a_home_press_that_wakes_the_screen_opens_nothing(self):
        buttons = powerd.Buttons()
        self.assertEqual(buttons.edge('home', True, 1.0, False), 'home')
        buttons.edge('home', False, 1.1, True)
        self.assertTrue(buttons.home_woke)
        buttons.edge('home', True, 5.0, True)
        self.assertFalse(buttons.home_woke)

    def test_power_alone_still_darkens_after_a_screenshot(self):
        edges = [('power', True, 1.0), ('home', True, 1.1), ('home', False, 1.3), ('power', False, 1.4),
                 ('power', True, 3.0), ('power', False, 3.2)]
        self.assertEqual(self.events(edges), ['home', 'screenshot', 'power'])

    def test_a_long_hold_does_nothing(self):
        self.assertEqual(self.events([('power', True, 1.0), ('power', False, 2.6)]), [])

    def test_a_dark_screen_wakes_on_the_press(self):
        self.assertEqual(self.events([('power', True, 1.0), ('power', False, 1.1)], lit=False), ['power'])

    def test_sleep_signal(self):
        signal = {'type': 'signal', 'member': 'PrepareForSleep', 'payload': {'type': 'b', 'data': [True]}}
        self.assertIs(powerd.parse_sleep_signal(json.dumps(signal)), True)
        signal['payload']['data'] = [False]
        self.assertIs(powerd.parse_sleep_signal(json.dumps(signal)), False)
        self.assertIsNone(powerd.parse_sleep_signal('{"member":"Other"}'))
        self.assertIsNone(powerd.parse_sleep_signal('Monitoring bus message stream.'))

    def test_logind_taking_its_name_is_seen(self):
        def owner(name, new):
            return json.dumps({'member': 'NameOwnerChanged', 'payload': {'data': [name, '', new]}})
        self.assertTrue(powerd.parse_logind_started(owner('org.freedesktop.login1', ':1.9')))
        self.assertFalse(powerd.parse_logind_started(owner('org.freedesktop.login1', '')))
        self.assertFalse(powerd.parse_logind_started(owner('org.other', ':1.9')))
        self.assertFalse(powerd.parse_logind_started('{"member":"NameOwnerChanged","payload":{"data":[]}}'))
        self.assertFalse(powerd.parse_logind_started('Monitoring bus message stream.'))

    def test_only_a_running_playback_stream_counts(self):
        def node(media, state):
            return {'info': {'state': state, 'props': {'media.class': media}}}
        self.assertTrue(powerd.streams_running(json.dumps([node('Stream/Output/Audio', 'running')])))
        for nodes in ([node('Stream/Output/Audio', 'idle')], [node('Stream/Input/Audio', 'running')],
                      [node('Audio/Sink', 'running')], [{'type': 'PipeWire:Interface:Core'}], []):
            self.assertFalse(powerd.streams_running(json.dumps(nodes)))
        self.assertFalse(powerd.streams_running('not json'))


class Integration(unittest.TestCase):
    def test_labwc_leaves_power_to_the_daemon_and_keeps_volume_on_the_lock_screen(self):
        tree = ET.fromstring((PROJECT / 'desktop/shell/labwc-rc.xml').read_bytes())
        self.assertEqual(tree.findall("./keyboard/keybind[@key='XF86PowerOff']"), [])
        home = tree.find("./keyboard/keybind[@key='XF86HomePage']")
        self.assertIsNone(home.get('allowWhenLocked'))
        for key in ('XF86AudioRaiseVolume', 'XF86AudioLowerVolume', 'XF86AudioMute'):
            self.assertEqual(tree.find(f"./keyboard/keybind[@key='{key}']").get('allowWhenLocked'), 'yes')
        greeter = ET.fromstring((PROJECT / 'desktop/greeter/labwc/rc.xml').read_bytes())
        for key in ('XF86PowerOff', 'XF86HomePage'):
            self.assertEqual(greeter.findall(f"./keyboard/keybind[@key='{key}']"), [])

    def test_a_held_key_on_the_lock_screen_wakes_once(self):
        view = (PROJECT / 'desktop/shell/shell/plugins/lock/LockView.qml').read_text()
        keys = view[view.index('Keys.onPressed'):]
        keys = keys[:keys.index('\n        }\n')]
        self.assertIn('if (!event.isAutoRepeat) root.wakeRequested()', keys)
        self.assertEqual(keys.count('wakeRequested()'), 1)

    def test_every_way_to_dark_uses_the_same_client_and_the_decided_times(self):
        client = '/usr/libexec/omarchy-powerctl'
        lock = (PROJECT / 'desktop/shell/shell/plugins/lock/Service.qml').read_text()
        idle = (PROJECT / 'desktop/shell/shell/plugins/services/idle/Service.qml').read_text()
        greeter = (PROJECT / 'desktop/greeter/shell.qml').read_text()
        self.assertIn(f'{client} idle', lock)
        self.assertIn(f'{client} idle', idle)
        self.assertIn(f'["{client}", "idle"]', greeter)
        self.assertIn('"1" ? 30000 : 5000', lock)
        self.assertRegex(greeter, r'IdleMonitor \{[^}]*timeout: 30\b')
        self.assertEqual(powerd.SETTLE_SECONDS, 10.0)

    def test_the_daemon_is_enabled_and_executable(self):
        from release.public_root import system_files
        self.assertIn("'omarchy-powerd.service'", (PROJECT / 'release/public_root.py').read_text())
        files = system_files()
        self.assertEqual(files['usr/libexec/omarchy-powerd'][1], 0o755)
        self.assertEqual(files['usr/libexec/omarchy-powerctl'][1], 0o755)
        self.assertEqual(files['usr/lib/systemd/system/omarchy-powerd.service'][1], 0o644)
        self.assertIn("multi-user.target.wants/omarchy-powerd.service", (PROJECT / 'release/audit.py').read_text())

    def test_assemble_enables_no_unit_of_the_overlay_which_joins_the_root_later(self):
        lines = [line for line in (PROJECT / 'system/assemble-rootfs').read_text().splitlines()
                 if 'systemctl --root' in line and ' enable ' in line]
        self.assertTrue(lines)
        overlay = PROJECT / 'system/overlay/usr/lib/systemd/system'
        for line in lines:
            for word in line.split():
                if word.endswith(('.service', '.socket', '.timer')):
                    self.assertFalse((overlay / word).exists(), word)
        unit = PROJECT / 'system/overlay/usr/lib/systemd/system/omarchy-powerd.service'
        self.assertIn('ExecStart=/usr/libexec/omarchy-powerd', unit.read_text())


class Brightness(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        work = Path(work.name)
        self.panel = work / 'backlight/panel'
        self.panel.mkdir(parents=True)
        (self.panel / 'brightness').write_text('20\n')
        (self.panel / 'max_brightness').write_text('2000\n')
        self.remembered = work / 'state/brightness'
        for target, value in (('BACKLIGHTS', work / 'backlight'), ('BRIGHTNESS', self.remembered),
                              ('FADE_SECONDS', 0), ('log', lambda *_: None)):
            patcher = patch.object(powerd, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.daemon = powerd.Daemon()

    def level(self):
        return int((self.panel / 'brightness').read_text())

    def test_the_first_boot_without_a_remembered_level_is_full_bright(self):
        self.daemon.restore_brightness()
        self.assertEqual(self.level(), 2000)

    def test_a_boot_restores_the_level_of_the_last_dark_not_the_dark_itself(self):
        (self.panel / 'brightness').write_text('1200\n')
        self.daemon.do_dark(None)
        self.assertEqual(self.level(), 0)
        self.assertEqual(self.remembered.read_text(), '1200\n')
        powerd.Daemon().restore_brightness()
        self.assertEqual(self.level(), 1200)

    def test_a_remembered_level_too_dim_to_see_is_raised(self):
        self.remembered.parent.mkdir()
        self.remembered.write_text('3\n')
        self.daemon.restore_brightness()
        self.assertEqual(self.level(), 100)

    def test_fade_is_eased_interruptible_and_keeps_requested_brightness(self):
        (self.panel / 'brightness').write_text('1200\n')
        with patch.object(powerd, 'FADE_SECONDS', .24), patch.object(powerd.time, 'monotonic', return_value=10):
            self.daemon.do_dark(None)
        self.assertEqual(self.level(), 1200)
        with patch.object(powerd, 'FADE_SECONDS', .24), patch.object(powerd.time, 'monotonic', return_value=10.12):
            self.daemon.tick_fade()
            self.assertAlmostEqual(self.level(), 600, delta=1)
            self.daemon.key_time = 10.12
            self.daemon.do_light(SETTLING)
        with patch.object(powerd, 'FADE_SECONDS', .24), patch.object(powerd.time, 'monotonic', return_value=10.36):
            self.daemon.tick_fade()
        self.assertEqual(self.level(), 1200)
        self.assertEqual(self.daemon.saved, 1200)

    def test_suspend_finishes_a_dark_transition_before_freezing(self):
        with patch.object(powerd, 'FADE_SECONDS', .24):
            self.daemon.do_dark(None)
            self.daemon.finish_dark_fade()
        self.assertEqual(self.level(), 0)
        self.assertIsNone(self.daemon.fade)

    def test_shutdown_keeps_a_changed_level_but_never_a_dark_panel(self):
        (self.panel / 'brightness').write_text('700\n')
        with self.assertRaises(SystemExit):
            self.daemon.stop_brightness()
        self.assertEqual(self.remembered.read_text(), '700\n')
        (self.panel / 'brightness').write_text('0\n')
        with self.assertRaises(SystemExit):
            self.daemon.stop_brightness()
        self.assertEqual(self.remembered.read_text(), '700\n')


class EventLoop(unittest.TestCase):
    """The real loop with a fake sysfs, keys through a pipe and no logind."""

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.panel = self.work / 'backlight/panel'
        self.panel.mkdir(parents=True)
        (self.panel / 'brightness').write_text('1563\n')
        (self.panel / 'max_brightness').write_text('3000\n')
        self.stats = self.work / 'stats'
        self.stats.mkdir()
        self.set_stats(3, 0)
        (self.work / 'wakeup_count').write_text('7\n')
        self.requests = []
        self.unit_state = 'activating'
        self.remembered = self.work / 'state/brightness'
        self.remembered.parent.mkdir()
        self.remembered.write_text('1563\n')
        for target, value in (('SETTLE_SECONDS', 0.1), ('FADE_SECONDS', 0), ('IDLE_GRACE_SECONDS', 0.1),
                              ('STATS', self.stats), ('BACKLIGHTS', self.work / 'backlight'),
                              ('BRIGHTNESS', self.remembered),
                              ('WAKEUP_COUNT', self.work / 'wakeup_count'), ('SOCKET', str(self.work / 'ctl')),
                              ('session_user', lambda: None), ('command', self.fake_command), ('log', lambda *_: None)):
            patcher = patch.object(powerd, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.daemon = powerd.Daemon()
        self.key_read, self.key_write = os.pipe()
        monitor_read, self.monitor_write = os.pipe()
        self.daemon.keys[self.key_read] = 'fake'
        self.daemon.take_inhibitor = self.daemon.release_inhibitor = lambda: None
        self.daemon.scan_keys = lambda: None
        monitor = open(monitor_read)
        def start_monitor():
            self.daemon.monitor = type('Monitor', (), {'stdout': monitor})
        self.daemon.start_monitor = start_monitor
        real_open = self.daemon.open_socket
        def open_socket():
            with patch.object(powerd.os, 'chown'), patch.object(powerd.grp, 'getgrnam') as group:
                group.return_value.gr_gid = 0
                return real_open()
        self.daemon.open_socket = open_socket
        loop = threading.Thread(target=self.daemon.run, daemon=True)
        def stop():
            self.daemon.stopping = True
            os.write(self.daemon.wake_write, b'.')
            loop.join(3)
            self.assertFalse(loop.is_alive())
            monitor.close()
            os.close(self.monitor_write)
        self.addCleanup(stop)
        loop.start()
        self.wait(lambda: Path(powerd.SOCKET).exists())

    def fake_command(self, *argv, **_):
        self.requests.append(argv)
        out = 's "yes"\n' if 'CanSuspend' in argv else 's ""\n'
        if 'ActiveState' in argv:
            out = self.unit_state + '\n'
        return subprocess.CompletedProcess(argv, 0, out, '')

    def set_stats(self, success, fail):
        for name, value in (('fail', fail), ('success', success)):  # atomic, like sysfs
            (self.stats / 'new').write_text(f'{value}\n')
            os.replace(self.stats / 'new', self.stats / name)

    def press(self, code=116, when=None):
        """A tap: the key goes down and comes up 50 ms later."""
        when = time.monotonic() if when is None else when
        up = when + 0.05
        os.write(self.key_write, powerd.INPUT_EVENT.pack(int(when), int(when % 1 * 1e6), 1, code, 1) +
                 powerd.INPUT_EVENT.pack(int(up), int(up % 1 * 1e6), 1, code, 0))

    def wait(self, condition, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.005)
        self.fail(f'not reached; state {self.daemon.machine.state}, requests {self.requests}')

    def brightness(self):
        return (self.panel / 'brightness').read_text().strip()

    def ask(self, request):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(powerd.SOCKET)
            connection.sendall(request.encode() + b'\n')
            return connection.recv(64).decode().strip()

    def test_press_sleep_wake(self):
        machine = self.daemon.machine
        self.assertEqual(self.ask('input'), 'lit')
        self.press()
        self.wait(lambda: self.brightness() == '0')
        self.assertEqual(self.ask('input'), 'dark')
        self.wait(lambda: ('systemctl', 'suspend') in self.requests)
        self.assertEqual(machine.state, SUSPENDING)
        # Asleep, then the wake key is the first thing the thawed daemon sees.
        self.press()
        self.wait(lambda: self.brightness() == '1563')
        self.assertEqual((machine.state, machine.inflight), (ON, True))
        # Pressed before it lit, delivered after: that wake took care of it.
        self.press(when=self.daemon.lit_at - 0.5)
        self.set_stats(4, 0)
        self.unit_state = 'inactive'
        self.wait(lambda: not machine.inflight)
        self.assertEqual((machine.state, self.brightness()), (ON, '1563'))
        # The next press is a new command.
        self.press()
        self.wait(lambda: self.brightness() == '0')

    def test_a_wake_without_a_button_stays_dark(self):
        self.press()
        self.wait(lambda: ('systemctl', 'suspend') in self.requests)
        self.set_stats(4, 0)
        self.unit_state = 'inactive'
        self.wait(lambda: not self.daemon.machine.inflight)
        self.assertEqual(self.brightness(), '0')
        self.assertIn(self.daemon.machine.state, (SETTLING, SUSPENDING))

    def test_a_failed_kernel_attempt_is_not_the_end_of_the_sleep(self):
        machine = self.daemon.machine
        self.press()
        self.wait(lambda: ('systemctl', 'suspend') in self.requests)
        count = self.work / 'wakeup_count'
        before = count.stat().st_mtime_ns
        time.sleep(0.01)
        self.set_stats(3, 1)  # systemd-sleep goes on to try again
        self.wait(lambda: count.stat().st_mtime_ns > before)  # armed again
        time.sleep(0.2)
        self.assertEqual((machine.state, machine.inflight), (SUSPENDING, True))
        self.press()  # the real wake
        self.wait(lambda: self.brightness() == '1563')
        self.assertEqual((machine.state, machine.inflight), (ON, True))
        self.set_stats(4, 1)
        self.unit_state = 'inactive'
        self.wait(lambda: not machine.inflight)

    def test_a_press_after_it_lit_darkens_while_the_sleep_finishes(self):
        self.press()
        self.wait(lambda: ('systemctl', 'suspend') in self.requests)
        self.press()
        self.wait(lambda: self.brightness() == '1563')
        self.press(when=time.monotonic() + 0.001)
        self.wait(lambda: self.brightness() == '0')
        self.assertTrue(self.daemon.machine.inflight)

    def test_a_suspend_from_elsewhere_arms_the_wakeup_count_and_a_press_lights(self):
        count = self.work / 'wakeup_count'
        count.write_text('9\n')
        before = count.stat().st_mtime_ns
        time.sleep(0.01)
        os.write(self.monitor_write, (json.dumps({'member': 'PrepareForSleep', 'payload': {'data': [True]}}) + '\n').encode())
        self.wait(lambda: self.brightness() == '0')
        self.assertGreater(count.stat().st_mtime_ns, before)
        self.press()
        self.wait(lambda: self.brightness() == '1563')
        self.assertEqual(self.daemon.machine.state, ON)

    def test_idle_through_the_socket_and_a_press_during_the_settle_time(self):
        self.assertEqual(self.ask('idle'), 'ok')
        self.wait(lambda: self.brightness() == '0')
        self.press()
        self.wait(lambda: self.brightness() == '1563')
        time.sleep(0.25)  # past the settle time: cancelled
        self.assertNotIn(('systemctl', 'suspend'), self.requests)
        self.assertEqual(self.daemon.machine.state, ON)


if __name__ == '__main__':
    unittest.main()
