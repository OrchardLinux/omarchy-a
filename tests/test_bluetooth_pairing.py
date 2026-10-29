import asyncio
import hashlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from release.j71b import public_root, audit

PROJECT = Path(__file__).resolve().parents[1]
policy = runpy.run_path(str(PROJECT / 'system/j71b/overlay/usr/lib/omarchy-bluetooth/policy.py'))
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
                             ('XF86HomePage', 'omarchy-tablet-power home')):  # also wakes a locked screen
            bindings = tree.findall("./keyboard/keybind[@key='%s']" % key)
            self.assertEqual(len(bindings), 1)
            self.assertEqual(bindings[0].get('onRelease'), 'yes')
            self.assertEqual(bindings[0].find('action').get('command'), command)
        for key in ('XF86AudioRaiseVolume', 'XF86AudioLowerVolume'):
            self.assertIsNone(tree.find("./keyboard/keybind[@key='%s']" % key).get('onRelease'))

    def test_public_sources_include_isolated_ui_and_pair_helper(self):
        replacements = public_root.desktop_replacements()
        self.assertIn('home/tablet/.local/share/omarchy-ipad/bin/omarchy-bluetooth-device', replacements)
        self.assertIn('home/tablet/.local/share/omarchy-ipad/shell/plugins/panels/bluetooth/Panel.qml', replacements)
        self.assertIn('home/tablet/.local/share/omarchy-ipad/shell/bluetooth-pairing/shell.qml', public_root.desktop_additions())
        files = public_root.system_files('test')
        self.assertEqual(files['usr/libexec/omarchy-bluetooth-pair'][1], 0o755)
        self.assertEqual(files['usr/lib/omarchy-bluetooth/policy.py'][1], 0o644)

    def test_labwc_component_has_corresponding_source_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'component'
            output.mkdir()
            names = ('labwc', 'LICENSE', 'source.tar.gz', '0001-cancel-super-tap-on-pointer.patch',
                     'packages.lock', 'compiler.txt', 'version.txt')
            digests = {}
            for name in names:
                data = ('fixture ' + name).encode()
                (output / name).write_bytes(data)
                digests[name] = hashlib.sha256(data).hexdigest()
            pin = {'version': 'test', 'sha256': digests['source.tar.gz'],
                   'patch_sha256': digests['0001-cancel-super-tap-on-pointer.patch']}
            source = root / 'desktop/labwc'
            source.mkdir(parents=True)
            (source / 'source.json').write_text(json.dumps(pin))
            record = {'schema': 1, 'source': pin, 'files': digests}
            (output / 'manifest.json').write_text(json.dumps(record))
            with patch.object(public_root, 'PROJECT', root), patch.object(audit, 'PROJECT', root):
                files = public_root.labwc_files(output)
                self.assertEqual(files['usr/bin/labwc'][1], 0o755)
                self.assertIn('usr/share/licenses/omarchy-labwc/source.tar.gz', files)
                hashes = {name: hashlib.sha256(value[0]).hexdigest() for name, value in files.items()}
                modes = {name: value[1] for name, value in files.items()}
                owners = {name: 0 for name in files}
                audit.verify_labwc(record, hashes, modes, owners, owners)
                modes['usr/bin/labwc'] = 0o777
                with self.assertRaises(ValueError):
                    audit.verify_labwc(record, hashes, modes, owners, owners)
                (output / 'labwc').write_bytes(b'tampered')
                with self.assertRaises(ValueError):
                    public_root.labwc_files(output)

    def test_dependency_preparation_and_tamper_detection(self):
        script = runpy.run_path(str(PROJECT / 'desktop/build-bluetooth-tools'))
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as wheel:
            wheel.writestr('dbus_next/__init__.py', '# fixture\n')
            wheel.writestr('dbus_next-0.2.3.dist-info/LICENSE', 'MIT fixture\n')
        pin = {'name': 'dbus-next', 'version': '0.2.3', 'sha256': hashlib.sha256(data.getvalue()).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'desktop/bluetooth').mkdir(parents=True)
            (root / 'desktop/bluetooth/dbus-next.json').write_text(json.dumps(pin))
            output = root / 'tools'
            script['prepare'](data.getvalue(), pin, output)
            with patch.object(public_root, 'PROJECT', root):
                files = public_root.bluetooth_files(output)
                self.assertIn('usr/lib/omarchy-bluetooth/dbus_next/__init__.py', files)
                self.assertIn('usr/share/licenses/omarchy-bluetooth-dbus-next/LICENSE', files)
                (output / 'lib/dbus_next/__init__.py').write_text('tampered')
                with self.assertRaises(ValueError):
                    public_root.bluetooth_files(output)
            with self.assertRaises(ValueError):
                script['prepare'](b'wrong', pin, root / 'wrong')
