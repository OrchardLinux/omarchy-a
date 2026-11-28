"""omarchy-powerd: the state machine (docs/power-and-lock.md) and its parsing."""
import struct
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

    def test_a_refused_sleep_is_asked_for_again_dark_and_locked(self):
        machine = asleep()
        self.assertEqual(machine.handle('suspend-refused'), ['take-inhibitor', 'arm-retry'])
        self.assertEqual((machine.state, machine.inflight, machine.no_suspend), (SETTLING, False, False))
        self.assertEqual(machine.handle('settle'), ['suspend'])
        self.assertEqual(machine.handle('suspend-refused'), ['take-inhibitor', 'arm-retry'])
        self.assertIn('light', machine.handle('power'))

    def test_a_board_that_cannot_sleep_stays_dark_until_pressed_without_asking_again(self):
        machine = asleep()
        self.assertEqual(machine.handle('suspend-unavailable'), ['take-inhibitor'])
        self.assertEqual((machine.state, machine.inflight, machine.no_suspend), (DARK, False, True))
        self.assertEqual(run(machine, 'settle', 'playing', 'not-playing'), [])
        self.assertEqual(machine.state, DARK)
        self.assertIn('light', machine.handle('power'))
        # The next lock asks again: it costs one question, not a freeze.
        self.assertEqual(run(machine, 'power', 'lock-ok', 'settle'), ['suspend'])

    def test_a_board_whose_suspend_keeps_aborting_backs_off_dark_and_locked(self):
        machine = asleep()
        for _ in range(powerd.ABORTS_BEFORE_DARK - 1):
            self.assertEqual(machine.handle('sleep-aborted'), ['take-inhibitor', 'arm-settle'])
            self.assertEqual(machine.handle('settle'), ['suspend'])
        # The third: dark and locked, asked for again only after the backoff.
        self.assertEqual(machine.handle('sleep-aborted'), ['take-inhibitor', 'arm-backoff'])
        self.assertEqual((machine.state, machine.inflight), (SETTLING, False))
        # The backoff's end asks once more; another abort backs off again at once.
        self.assertEqual(machine.handle('settle'), ['suspend'])
        self.assertEqual(machine.handle('sleep-aborted'), ['take-inhibitor', 'arm-backoff'])
        # Playback ending meanwhile does not shorten it.
        run(machine, 'playing')
        self.assertEqual(machine.handle('not-playing'), ['arm-backoff'])
        # A press lights as usual and starts the count again.
        self.assertIn('light', machine.handle('home'))
        self.assertEqual(machine.aborts, 0)
        self.assertEqual(run(machine, 'power', 'lock-ok', 'settle'), ['suspend'])

    def test_a_sleep_that_happened_ends_the_backoff(self):
        machine = asleep()
        for _ in range(powerd.ABORTS_BEFORE_DARK):
            run(machine, 'sleep-aborted', 'settle')
        self.assertEqual(machine.handle('sleep-ended'), ['take-inhibitor', 'arm-settle'])
        self.assertEqual(machine.aborts, 0)

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

    def test_power_and_home_come_from_any_device_that_has_them(self):
        # The iPad's buttons (gpio-keys: Power), the simulator's QEMU keyboard
        # (every key), and devices without either: a touchscreen, a mouse.
        self.assertTrue(powerd.reports_keys('10000000000000 0\n'))
        self.assertTrue(powerd.reports_keys('ffffffffff ffffffffffffffff ffffffffffffffff fffffffffffffffe\n'))
        self.assertTrue(powerd.reports_keys('100000000000 0 0\n'))  # KEY_HOMEPAGE alone (bit 172)
        self.assertFalse(powerd.reports_keys('30400 1f0000 0 0 0 0\n'))
        self.assertFalse(powerd.reports_keys('1f0000 0 0 0 0\n'))
        self.assertFalse(powerd.reports_keys(''))

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

    def test_a_short_volume_down_and_power_press_takes_one_screenshot(self):
        for edges in ([('power', True, 1.0), ('volume-down', True, 1.1), ('power', False, 1.3), ('volume-down', False, 1.4)],
                      [('volume-down', True, 1.0), ('power', True, 1.05), ('volume-down', False, 1.3), ('power', False, 1.35)]):
            with self.subTest(edges=edges):
                self.assertEqual(self.events(edges), ['screenshot'])

    def test_volume_down_and_power_held_do_nothing(self):
        edges = [('volume-down', True, 1.0), ('power', True, 1.1), ('power', False, 11), ('volume-down', False, 11)]
        self.assertEqual(self.events(edges), [])

    def test_volume_down_alone_is_no_event(self):
        self.assertEqual(self.events([('volume-down', True, 1.0), ('volume-down', False, 1.1)]), [])
        edges = [('volume-down', True, 1.0), ('volume-down', False, 1.1), ('power', True, 2.0), ('power', False, 2.1)]
        self.assertEqual(self.events(edges), ['power'])

    def test_volume_down_and_power_is_no_home_combination(self):
        buttons = powerd.Buttons()
        for name, down, when in (('power', True, 1.0), ('volume-down', True, 1.1), ('volume-down', False, 1.3), ('power', False, 1.4)):
            buttons.edge(name, down, when, True)
        self.assertFalse(buttons.home_in_combo)
        self.assertEqual(self.events([('home', True, 3.0), ('home', False, 3.1)]), ['home', 'home-up'])

    def test_the_volume_keys_device_is_read(self):
        width = struct.calcsize('L') * 8
        words = [0] * 4
        words[-1 - powerd.KEY_VOLUMEDOWN // width] |= 1 << powerd.KEY_VOLUMEDOWN % width
        self.assertTrue(powerd.reports_keys(' '.join('%x' % w for w in words)))
        self.assertEqual(powerd.key_edges(powerd.INPUT_EVENT.pack(5, 0, powerd.EV_KEY, powerd.KEY_VOLUMEDOWN, 1)),
                         [('volume-down', True, 5.0)])

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
        self.assertIsNone(buttons.edge('home', False, 1.1, True))
        self.assertTrue(buttons.home_woke)
        buttons.edge('home', True, 5.0, True)
        self.assertFalse(buttons.home_woke)

    def test_home_let_go_after_a_press_alone_is_the_home_action(self):
        self.assertEqual(self.events([('home', True, 1.0), ('home', False, 1.1)]), ['home', 'home-up'])
        # A release whose press was not seen (powerd started meanwhile) is not one.
        self.assertEqual(self.events([('home', False, 1.1)]), [])

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

    def test_a_held_key_on_the_lock_screen_wakes_once(self):
        view = (PROJECT / 'desktop/shell/shell/plugins/lock/LockView.qml').read_text()
        start = view.index('Keys.onPressed')
        indent = start - view.rindex('\n', 0, start) - 1
        keys = view[start:]
        keys = keys[:keys.index('\n' + ' ' * indent + '}\n')]
        self.assertIn('if (!event.isAutoRepeat) root.wakeRequested()', keys)
        self.assertEqual(keys.count('wakeRequested()'), 1)

    def test_every_way_to_dark_uses_the_same_client_and_the_decided_times(self):
        client = '/usr/libexec/omarchy-powerctl'
        lock = (PROJECT / 'desktop/shell/shell/plugins/lock/Service.qml').read_text()
        idle = (PROJECT / 'desktop/shell/shell/plugins/services/idle/Service.qml').read_text()
        self.assertIn(f'{client} idle', lock)
        self.assertIn(f'{client} idle', idle)
        self.assertIn('"1" ? 30000 : 5000', lock)
        self.assertEqual(powerd.SETTLE_SECONDS, 10.0)

    def test_a_new_installs_first_lock_stays_lit_ten_minutes_until_its_first_unlock(self):
        lock = (PROJECT / 'desktop/shell/shell/plugins/lock/Service.qml').read_text()
        self.assertIn('readonly property int firstLockMs: 600000', lock)
        self.assertIn('stateHome + "/omarchy/first-lock-done"', lock)
        self.assertIn('path: root.startLocked ? root.firstLockMark : ""', lock)
        self.assertIn('firstLock ? Math.max(interval, firstLockMs) : interval', lock)
        unlock = lock[lock.index('function finishUnlock()'):]
        self.assertIn('firstLockDone.running = true', unlock[:unlock.index('\n  }\n')])

    def test_the_daemon_is_enabled_and_executable(self):
        from package_tree import system_files
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

    def test_a_fade_writes_once_a_frame_however_often_the_loop_turns(self):
        # Each backlight write is a kernel uevent that wakes the loop again at once.
        writes = []
        real_write = Path.write_text

        def write_text(path, data, *args, **kwargs):
            writes.append(data)
            return real_write(path, data, *args, **kwargs)
        (self.panel / 'brightness').write_text('1200\n')
        with patch.object(powerd, 'FADE_SECONDS', .24), patch.object(Path, 'write_text', write_text):
            with patch.object(powerd.time, 'monotonic', return_value=10):
                self.daemon.do_dark(None)
                self.daemon.tick_fade()
            first = len(writes)
            for i in range(1000):  # a busy loop within one frame
                with patch.object(powerd.time, 'monotonic', return_value=10 + i * 1e-5):
                    self.daemon.tick_fade()
            self.assertEqual(len(writes), first)
            with patch.object(powerd.time, 'monotonic', return_value=10 + powerd.FRAME_SECONDS + 1e-6):
                self.assertEqual(self.daemon.next_frame(), 0)
                self.daemon.tick_fade()
            self.assertEqual(len(writes), first + 1)
            with patch.object(powerd.time, 'monotonic', return_value=10.3):
                self.daemon.tick_fade()  # the last frame is written whenever it is due
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

    def test_a_restart_while_dimmed_leaves_the_users_level_for_the_next_daemon(self):
        # An update restarts the daemon; the next one knows nothing of the dim.
        (self.panel / 'brightness').write_text('1600\n')
        self.daemon.dim_saved, self.daemon.dim_level = 1600, 1000
        (self.panel / 'brightness').write_text('1000\n')
        with self.assertRaises(SystemExit):
            self.daemon.stop_brightness()
        self.assertEqual(self.level(), 1600)
        self.assertEqual(self.remembered.read_text(), '1600\n')

    def test_a_restart_in_the_dark_or_mid_fade_comes_back_lit_at_the_users_level(self):
        socket_path = self.remembered.parent.parent / 'ctl'
        socket_path.write_text('')  # the socket outlives a restart, not a boot
        for fade in (0, .24):
            with self.subTest(fade=fade):
                (self.panel / 'brightness').write_text('1200\n')
                daemon = powerd.Daemon()
                with patch.object(powerd, 'FADE_SECONDS', fade):
                    daemon.do_dark(None)
                    daemon.tick_fade()
                with self.assertRaises(SystemExit):
                    daemon.stop_brightness()
                self.assertEqual(self.level(), 0)
                with patch.object(powerd, 'SOCKET', str(socket_path)):
                    powerd.Daemon().start_lit()
                self.assertEqual(self.level(), 1200)


class SleepAccounting(unittest.TestCase):
    """How long a suspend in flight has been awake, and what that may conclude."""

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.stats = Path(work.name)
        for name, value in (('success', 3), ('fail', 0)):
            (self.stats / name).write_text(f'{value}\n')
        self.logs = []
        for target, value in (('STATS', self.stats), ('log', self.logs.append)):
            patcher = patch.object(powerd, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.daemon = powerd.Daemon()
        self.fed = []

        def feed(event):  # what the machine does with them: the suspend is no longer in flight
            self.fed.append(event)
            self.daemon.machine.inflight = False
        self.daemon.feed = feed
        self.daemon.machine.inflight = True
        self.daemon.begin_sleep_record()
        self.daemon.watching_unit = True  # no unit watcher thread here
        self.daemon.last_turn = 1000.0

    def turns(self, count, step, start=None):
        now = self.daemon.last_turn if start is None else start
        for _ in range(count):
            now += step
            self.daemon.count_awake(now)
        return now

    def test_a_busy_loop_is_not_time_awake(self):
        self.turns(20000, 0.0005)  # 20000 turns in 10 s
        self.assertAlmostEqual(self.daemon.awake, 10, delta=0.01)
        self.assertEqual(self.fed, [])

    def test_a_freeze_or_a_clock_that_runs_in_sleep_is_not_time_awake(self):
        self.turns(1, 3600.0)  # frozen, or asleep on a kernel whose clock runs on
        self.turns(1, -5.0)    # and never negative
        self.assertLessEqual(self.daemon.awake, powerd.AWAKE_STEP_MAX)
        self.assertEqual(self.fed, [])

    def test_a_suspend_not_begun_in_30_s_awake_did_not_happen(self):
        self.turns(int(29.9 / powerd.TICK_SECONDS), powerd.TICK_SECONDS)
        self.assertEqual(self.fed, [])
        self.turns(10, powerd.TICK_SECONDS)
        self.assertEqual(self.fed, ['timeout'])
        self.assertTrue(any('suspend did not happen' in line for line in self.logs))

    def test_a_sleep_that_began_ends_only_by_its_end(self):
        self.turns(200, powerd.TICK_SECONDS)
        self.daemon.sleep_began('logind')
        self.assertEqual(self.daemon.awake, 0)
        self.turns(int(100 / powerd.TICK_SECONDS), powerd.TICK_SECONDS)  # a wake press, a slow resume
        self.assertEqual(self.fed, [])
        (self.stats / 'success').write_text('4\n')
        self.daemon.sleep_finished('logind')
        self.assertEqual(self.fed, ['sleep-ended'])
        self.assertTrue(any(line.startswith('sleep-ended result=slept ') and 'end=logind' in line
                            for line in self.logs), self.logs)

    def test_an_end_never_seen_is_concluded_from_the_counters_at_last(self):
        self.daemon.sleep_began('kernel')
        (self.stats / 'fail').write_text('1\n')
        self.turns(int((powerd.SLEEP_END_AWAKE_SECONDS + 1) / powerd.TICK_SECONDS), powerd.TICK_SECONDS)
        self.assertEqual(self.fed, ['sleep-aborted'])
        self.assertTrue(any(line.startswith('sleep-ended result=aborted ') and 'end=none' in line
                            for line in self.logs), self.logs)

    def test_every_line_of_a_read_from_the_monitor_is_seen(self):
        read, write = os.pipe()
        self.addCleanup(os.close, read)
        self.addCleanup(os.close, write)
        self.daemon.monitor = type('Monitor', (), {'stdout': open(read, 'rb', buffering=0, closefd=False)})
        seen = []
        self.daemon.monitor_line = seen.append
        prepare = json.dumps({'member': 'PrepareForSleep', 'payload': {'data': [False]}})
        os.write(write, ('{"member": "NameOwnerChanged"}\n' + prepare + '\n{"memb').encode())
        self.daemon.read_monitor()
        self.assertEqual(seen, ['{"member": "NameOwnerChanged"}', prepare])
        os.write(write, b'er": "x"}\n')
        self.daemon.read_monitor()
        self.assertEqual(seen[-1], '{"member": "x"}')


class SuspendRequest(unittest.TestCase):
    def test_only_a_board_that_cannot_sleep_is_told_from_a_refusal_for_now(self):
        for answer, event in (('s "na"', 'suspend-unavailable'), ('s "no"', 'suspend-unavailable'),
                              ('s "challenge"', 'suspend-refused'), ('', 'suspend-refused')):
            daemon, posted = powerd.Daemon(), []
            daemon.post = posted.append
            reply = subprocess.CompletedProcess([], 0, answer + '\n', '')
            with patch.object(powerd, 'command', return_value=reply), patch.object(powerd, 'log'):
                daemon.request_suspend()
            self.assertEqual(posted, [event], answer)


class LogindSleep(unittest.TestCase):
    """logind refuses a delay inhibitor while its sleep runs ("already running")."""

    def setUp(self):
        self.daemon = powerd.Daemon()
        self.started = []
        alive = type('Alive', (), {'poll': lambda self: None, 'terminate': lambda self: None,
                                   'wait': lambda self: 0})
        patcher = patch.object(powerd.subprocess, 'Popen', side_effect=lambda *_: self.started.append(1) or alive())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_inhibitor_waits_for_loginds_end_of_the_sleep(self):
        daemon = self.daemon
        daemon.logind_asleep = True
        daemon.take_inhibitor()
        daemon.keep_inhibitor()
        self.assertEqual(self.started, [])
        daemon.logind_asleep = False  # PrepareForSleep(false)
        daemon.keep_inhibitor()
        self.assertEqual(len(self.started), 1)

    def test_without_loginds_end_it_is_asked_a_while_after_systemd_suspend_ended(self):
        daemon = self.daemon
        daemon.logind_asleep = True
        daemon.take_inhibitor()
        daemon.logind_busy_until = time.monotonic() - 1  # set by sleep_finished('unit'), now past
        daemon.keep_inhibitor()
        self.assertEqual(len(self.started), 1)


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
        def stop_loop():
            self.daemon.stopping = True
            os.write(self.daemon.wake_write, b'.')
            loop.join(3)
            self.assertFalse(loop.is_alive())
        self.stop_loop = stop_loop
        def stop():
            stop_loop()
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

    def test_home_alone_starts_the_home_action_and_a_screenshot_chord_does_not(self):
        # The action comes from the button: no labwc binding or keyboard
        # state in between. Half of Home + Power starts nothing.
        user = pwd.struct_passwd(('tablet', 'x', 1000, 1000, '', '/home/tablet', '/bin/bash'))
        spawned = []
        with patch.object(powerd, 'session_user', lambda: user), \
                patch.object(powerd, 'spawn_as_user', lambda *argv, **options: spawned.append((argv, options))):
            when = time.monotonic()
            event = powerd.INPUT_EVENT.pack
            os.write(self.key_write, b''.join(event(int(when+i/10), int((when+i/10)%1*1e6), 1, code, down)
                         for i, (code, down) in enumerate(((116, 1), (172, 1), (172, 0), (116, 0)))))
            self.wait(lambda: self.daemon.buttons.home_in_combo)
            self.assertEqual(spawned, [])
            self.press(172)
            self.wait(lambda: spawned)
        self.assertEqual(spawned[0][0][1:], ('omarchy-home-button',))
        self.assertEqual(self.ask('status'), 'ON')

    def test_idle_dim_halves_the_range_and_any_input_restores_the_level(self):
        self.assertEqual(self.ask('dim'), 'ok')
        self.assertEqual(self.brightness(), '1500')
        self.assertEqual(self.ask('als-state'), 'dark')
        self.assertEqual(self.ask('brightness panel 600 1500'), 'held')
        self.ask('undim'); self.assertEqual(self.brightness(), '1563')
        # A level changed while dimmed is still restored: a touch must never leave the panel dim.
        self.ask('dim')
        (self.panel / 'brightness').write_text('700\n')
        self.ask('undim'); self.assertEqual(self.brightness(), '1563')

    def test_idle_dim_never_brightens_a_panel_already_at_half_or_below(self):
        (self.panel / 'brightness').write_text('900\n')
        self.assertEqual(self.ask('dim'), 'ok')
        self.assertEqual(self.brightness(), '900')
        self.ask('undim'); self.assertEqual(self.brightness(), '900')

    def test_the_idle_dim_comes_ten_seconds_before_the_lock(self):
        idle = (PROJECT / 'desktop/shell/shell/plugins/services/idle/Service.qml').read_text()
        self.assertIn('timeout: Math.max(1, root.lockTimeoutSeconds - 10)', idle)

    def test_automatic_brightness_obeys_power_state_and_manual_changes(self):
        self.assertEqual(self.ask('brightness panel 1800 1563'), 'ok')
        self.assertEqual(self.brightness(), '1800')
        self.assertEqual(self.ask('brightness panel 1900 1563'), 'held')
        self.assertEqual(self.brightness(), '1800')
        for request in ('brightness panel 0 1800', 'brightness panel 3001 1800',
                        'brightness other 1900 1800', 'brightness panel ² 1800'):
            self.assertEqual(self.ask(request), 'held')
            self.assertEqual(self.brightness(), '1800')
        self.press(); self.wait(lambda: self.brightness() == '0')
        self.assertEqual(self.ask('brightness panel 1800 0'), 'held')
        self.assertEqual(self.brightness(), '0')


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

    def test_the_wake_fade_while_the_sleep_finishes_neither_spins_nor_ends_it(self):
        # The kernel sends a uevent for every backlight write (backlight_generate_event) to the
        # socket this loop watches: counted in loop turns, the 30 s ran out within the wake's fade.
        logs, turns = [], []
        ours, kernel = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.addCleanup(kernel.close)
        self.addCleanup(ours.close)
        self.addCleanup(self.stop_loop)  # runs first: the loop must not watch a closed socket
        ours.setblocking(False)
        kernel.setblocking(False)
        brightness = self.panel / 'brightness'
        real_write = Path.write_text

        def write_text(path, data, *args, **kwargs):
            result = real_write(path, data, *args, **kwargs)
            if path == brightness:
                try:
                    kernel.send(b'change@/devices/backlight/panel\0ACTION=change\0SUBSYSTEM=backlight\0SOURCE=sysfs\0')
                except BlockingIOError:
                    pass
            return result
        real_watch = self.daemon.watch_kernel

        def watch_kernel():  # once a turn of the loop
            turns.append(1)
            real_watch()
        with patch.object(Path, 'write_text', write_text), patch.object(powerd, 'FADE_SECONDS', 0.24), \
                patch.object(powerd, 'log', logs.append):
            self.daemon.uevents = ours
            self.daemon.watch_kernel = watch_kernel
            self.press()
            self.wait(lambda: ('systemctl', 'suspend') in self.requests)
            self.set_stats(4, 0)  # it slept and resumed; systemd-suspend still runs
            before = len(turns)
            self.press()  # the wake
            self.wait(lambda: self.brightness() == '1563')
            time.sleep(0.1)
            self.assertLess(len(turns) - before, 200)
            self.unit_state = 'inactive'
            self.wait(lambda: not self.daemon.machine.inflight)
        self.assertTrue(any(line.startswith('sleep-ended result=slept ') for line in logs), logs)
        self.assertFalse(any('did not happen' in line for line in logs), logs)

    def test_a_sleep_logind_announced_ends_with_loginds_end_also_after_a_wake_press(self):
        logs = []

        def prepare_for_sleep(sleeping):
            os.write(self.monitor_write, (json.dumps({'member': 'PrepareForSleep',
                                                      'payload': {'data': [sleeping]}}) + '\n').encode())
        with patch.object(powerd, 'log', logs.append):
            self.unit_state = 'inactive'  # systemd-suspend has not started yet: that is not its end
            self.press()
            self.wait(lambda: ('systemctl', 'suspend') in self.requests)
            prepare_for_sleep(True)
            self.wait(lambda: self.daemon.sleep_begun and self.daemon.logind_asleep)
            time.sleep(0.3)
            self.assertTrue(self.daemon.machine.inflight)
            self.unit_state = 'activating'
            self.set_stats(4, 0)
            self.press()  # the wake: lit at once, the sleep still finishing
            self.wait(lambda: self.brightness() == '1563')
            self.assertEqual((self.daemon.machine.state, self.daemon.machine.inflight), (ON, True))
            prepare_for_sleep(False)
            self.wait(lambda: not self.daemon.machine.inflight)
        self.assertFalse(self.daemon.logind_asleep)
        self.assertTrue(any(line.startswith('sleep-ended result=slept ') and 'end=logind' in line
                            for line in logs), logs)
        self.assertFalse(any('did not happen' in line for line in logs), logs)


if __name__ == '__main__':
    unittest.main()


class LockedUsb(unittest.TestCase):
    def test_new_usb_devices_are_off_while_locked_and_on_after_unlock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for host in ('usb1', 'usb2'):
                (root / host).mkdir()
                (root / host / 'authorized_default').write_text('1')
            with patch.object(powerd, 'USB_DEVICES', root):
                powerd.usb_new_devices(False)
                self.assertEqual({(root / h / 'authorized_default').read_text() for h in ('usb1', 'usb2')}, {'0'})
                powerd.usb_new_devices(True)
                self.assertEqual({(root / h / 'authorized_default').read_text() for h in ('usb1', 'usb2')}, {'1'})

    def test_the_lock_screen_reports_the_unlock(self):
        service = (PROJECT / 'desktop/shell/shell/plugins/lock/Service.qml').read_text()
        self.assertIn('"/usr/libexec/omarchy-powerctl", "unlocked"', service)
        self.assertIn("request == 'unlocked'", PATH.read_text())
