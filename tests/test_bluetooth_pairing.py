import asyncio
import json
from pathlib import Path
import runpy
import unittest
import xml.etree.ElementTree as ET


PROJECT = Path(__file__).resolve().parents[1]
policy = runpy.run_path(str(PROJECT / 'system/overlay/usr/lib/omarchy-bluetooth/policy.py'))
PromptBroker, Rejected = policy['PromptBroker'], policy['Rejected']


class PairingPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmation_never_auto_approves_and_stale_replies_do_nothing(self):
        events = []
        broker = PromptBroker(events.append)
        task = asyncio.create_task(broker.request('confirm', code='123456'))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertFalse(broker.reply({'id': 'stale', 'accept': True}))
        self.assertFalse(task.done())
        self.assertTrue(broker.reply({'id': events[0]['id'], 'accept': True}))
        self.assertIsNone(await task)
        self.assertEqual(events[-1], {'event': 'clear'})

    async def test_rejection_cancellation_and_concurrent_request(self):
        for cancel in (False, True):
            events = []
            broker = PromptBroker(events.append)
            task = asyncio.create_task(broker.request('authorize'))
            await asyncio.sleep(0)
            with self.assertRaises(Rejected):
                await broker.request('confirm')
            if cancel:
                broker.cancel()
            else:
                broker.reply({'id': events[0]['id'], 'accept': False})
            with self.assertRaises(Rejected):
                await task
            self.assertIsNone(broker.pending)

    async def test_invalid_passkey_can_be_corrected_without_leaking_value(self):
        events = []
        broker = PromptBroker(events.append)
        task = asyncio.create_task(broker.request('passkey'))
        await asyncio.sleep(0)
        request = events[0]['id']
        self.assertFalse(broker.reply({'id': request, 'accept': True, 'value': '9999999'}))
        self.assertFalse(task.done())
        self.assertNotIn('9999999', json.dumps(events))
        broker.reply({'id': request, 'accept': True, 'value': '000042'})
        self.assertEqual(await task, 42)

    def test_codes_and_incomplete_pairing_policy(self):
        for value in ('', '1234567', '-1', '1.5', '\u0661', None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy['response_value']('passkey', value)
        self.assertEqual(policy['response_value']('pin', '0000'), '0000')
        for value in ('', 'a' * 17, '\n', '\u0000'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                policy['response_value']('pin', value)
        self.assertTrue(policy['needs_repair']({'Paired': True, 'Bonded': False}))
        self.assertTrue(policy['needs_repair']({'Trusted': True, 'Bonded': False}))
        self.assertFalse(policy['needs_repair']({'Paired': True, 'Trusted': True, 'Bonded': True}))
        self.assertFalse(policy['needs_repair']({}))


class PairingPackagingTests(unittest.TestCase):
    def test_named_release_bindings_and_brightness_repeat(self):
        tree = ET.fromstring((PROJECT / 'desktop/shell/labwc-rc.xml').read_bytes())
        for key, command in (('Super_L', 'omarchy-shell omarchy.dock apps'),
                             ('Super_R', 'omarchy-shell omarchy.dock apps'),
                             ('XF86HomePage', 'omarchy-shell omarchy.dock apps')):
            bindings = tree.findall("./keyboard/keybind[@key='%s']" % key)
            self.assertEqual(len(bindings), 1)
            self.assertEqual(bindings[0].get('onRelease'), 'yes')
            if key == 'XF86HomePage':
                # The dock, unless the press was part of Home + Power (a screenshot).
                self.assertEqual(bindings[0].find('action').get('command'), 'omarchy-home-button')
                self.assertIn(command, (PROJECT / 'desktop/shell/bin/omarchy-home-button').read_text())
            else:
                self.assertEqual(bindings[0].find('action').get('command'), command)
        for key in ('XF86AudioRaiseVolume', 'XF86AudioLowerVolume'):
            self.assertIsNone(tree.find("./keyboard/keybind[@key='%s']" % key).get('onRelease'))

    def test_public_sources_include_isolated_ui_and_pair_helper(self):
        # The whole Omarchy tree is the package's, the pairing UI with it.
        for name in ('bin/omarchy-bluetooth-device', 'shell/plugins/panels/bluetooth/Panel.qml',
                     'shell/bluetooth-pairing/shell.qml'):
            self.assertTrue((PROJECT / 'desktop/shell' / name).is_file(), name)
        from package_tree import system_files
        files = system_files()
        self.assertEqual(files['usr/libexec/omarchy-bluetooth-pair'][1], 0o755)
        self.assertEqual(files['usr/lib/omarchy-bluetooth/policy.py'][1], 0o644)

    def test_the_library_is_installed_from_its_wheel(self):
        # The recipe fetches the pinned wheel; desktop/install-tree takes every module of it.
        from package_tree import system_files
        files = system_files()
        for name in ('usr/lib/omarchy-bluetooth/dbus_next/__init__.py', 'usr/lib/omarchy-bluetooth/dbus_next/aio/__init__.py',
                     'usr/share/licenses/omarchy-bluetooth-dbus-next/LICENSE'):
            self.assertEqual(files[name][1], 0o644, name)


class Reconnect(unittest.TestCase):
    def test_bonded_devices_can_reconnect_quickly(self):
        conf = (PROJECT / 'system/overlay/etc/bluetooth/main.conf').read_text()
        self.assertIn('FastConnectable = true', conf)
        self.assertIn('AutoEnable = true', conf)
