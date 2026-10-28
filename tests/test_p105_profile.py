"""P105 ABI, payload integrity and build-container safeguards."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
PROFILE = PROJECT / 'desktop/p105'
PREPARE = PROJECT / 'system/p105/prepare-root'
spec = importlib.util.spec_from_file_location('p105_stage', PROFILE / 'stage.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


def arm_elf(machine=40, flags=0x05000400):
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    return struct.pack('<16sHHIIIIIHHHHHH', ident, 3, machine, 1, 0, 52, 0,
                       flags, 52, 32, 1, 40, 0, 0)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class P105ProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def payload(self):
        files = {
            stage.KEYBOARD.as_posix(): arm_elf(),
            'usr/bin/labwc': arm_elf(),
            'usr/bin/labwc-copy': arm_elf(),
            'usr/libexec/omarchy-wtype': arm_elf(),
            'usr/share/doc/omarchy-p105/support-build.json': b'{"schema":1}\n',
            'home/tablet/.config/labwc/autostart': b'#!/bin/sh\nquickshell\n',
        }
        record = {
            'schema': 1, 'profile': 'p105', 'architecture': 'armv7h',
            'keyboard_sha256': digest(files[stage.KEYBOARD.as_posix()]),
            'support_manifest_sha256': digest(files['usr/share/doc/omarchy-p105/support-build.json']),
            'symlinks': {'usr/local/bin/compositor': '../../bin/labwc'},
        }
        files[stage.RECEIPT] = json.dumps(record).encode()
        for name, data in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        link = self.root / 'usr/local/bin/compositor'
        link.parent.mkdir(parents=True)
        link.symlink_to(record['symlinks']['usr/local/bin/compositor'])
        (self.root / stage.MANIFEST).write_text(json.dumps({name: digest(data) for name, data in files.items()}))

    def verify(self):
        with contextlib.redirect_stdout(io.StringIO()):
            stage.verify(self.root)

    def rewrite_receipt(self, field, value):
        path = self.root / stage.RECEIPT
        record = json.loads(path.read_text())
        record[field] = value
        path.write_text(json.dumps(record))
        manifest_path = self.root / stage.MANIFEST
        manifest = json.loads(manifest_path.read_text())
        manifest[stage.RECEIPT] = digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))

    def test_only_little_endian_elf32_arm_hard_float_is_accepted(self):
        binary = self.root / 'program'
        valid = arm_elf()
        binary.write_bytes(valid)
        stage.check_armhf(binary)
        for label, content in (
            ('truncated', valid[:51]),
            ('ELF64', valid[:4] + b'\x02' + valid[5:]),
            ('big endian', valid[:5] + b'\x02' + valid[6:]),
            ('AArch64', arm_elf(machine=183)),
            ('x86', arm_elf(machine=3)),
            ('unspecified float ABI', arm_elf(flags=0x05000000)),
            ('soft float', arm_elf(flags=0x05000200)),
            ('conflicting float flags', arm_elf(flags=0x05000600)),
        ):
            with self.subTest(format=label):
                binary.write_bytes(content)
                with self.assertRaises(ValueError):
                    stage.check_armhf(binary)

    def test_payload_changes_missing_files_and_added_files_are_rejected(self):
        self.payload()
        self.verify()
        path = self.root / 'home/tablet/.config/labwc/autostart'
        original = path.read_bytes()
        for content in (b'changed launcher', None):
            with self.subTest(content=content):
                if content is None:
                    path.unlink()
                else:
                    path.write_bytes(content)
                with self.assertRaisesRegex(ValueError, 'files differ'):
                    self.verify()
                path.write_bytes(original)
        (self.root / 'unexpected-helper').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'files differ'):
            self.verify()

    def test_symlink_retargeting_and_unrecorded_dangling_links_are_rejected(self):
        self.payload()
        link = self.root / 'usr/local/bin/compositor'
        link.unlink()
        # Both destinations contain identical bytes; the link itself is pinned.
        link.symlink_to('../../bin/labwc-copy')
        with self.assertRaisesRegex(ValueError, 'symlinks differ'):
            self.verify()
        link.unlink()
        link.symlink_to('../../bin/labwc')
        (self.root / 'unrecorded-link').symlink_to('missing-file')
        with self.assertRaisesRegex(ValueError, 'symlinks differ'):
            self.verify()

    def test_receipt_profile_and_component_hashes_are_checked(self):
        self.payload()
        original = json.loads((self.root / stage.RECEIPT).read_text())
        for field, value in (('architecture', 'aarch64'), ('profile', 'j71b'),
                             ('keyboard_sha256', '0' * 64),
                             ('support_manifest_sha256', '0' * 64)):
            with self.subTest(field=field):
                self.rewrite_receipt(field, value)
                with self.assertRaises(ValueError):
                    self.verify()
                self.rewrite_receipt(field, original[field])

    def test_menu_routes_supported_panels_and_excludes_unavailable_power_actions(self):
        menu = self.root / 'menu.jsonc'
        shutil.copyfile(PROJECT / 'desktop/shell/default/omarchy/omarchy-menu.jsonc', menu)
        stage.adapt_menu(menu)
        entries = json.loads(menu.read_text())
        for panel in ('monitor', 'network', 'bluetooth', 'power'):
            key = 'setup.monitors' if panel == 'monitor' else 'setup.' + panel
            self.assertEqual(entries[key]['action'], 'omarchy-shell omarchy.%s toggle' % panel)
        power = {name: row['action'] for name, row in entries.items() if name.startswith('system.')}
        self.assertEqual(power, {'system.shutdown': 'omarchy-system shutdown'})
        for action in ('reboot', 'suspend', 'hibernate', 'logout'):
            with self.subTest(action=action):
                result = subprocess.run(['bash', str(PROFILE / 'system-action'), action],
                                        text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn('install', entries)
        self.assertNotIn('update', entries)

    def test_firefox_defaults_preserve_omafox_and_other_policies_and_preferences(self):
        source = PROJECT / 'desktop/configuration/firefox-policies.json'
        original = source.read_bytes()
        document = json.loads(original)
        extensions = document['policies']['ExtensionSettings']
        homepage = {'URL': 'https://example.invalid/', 'Locked': False}
        retained = {
            'browser.custom.pref': {'Value': 'keep', 'Status': 'default', 'Type': 'string'},
            'fission.autostart': {'Value': True, 'Status': 'default', 'Type': 'boolean'},
            'security.sandbox.content.level': {'Value': 4, 'Status': 'default', 'Type': 'number'},
        }
        document['policies'].update(Homepage=homepage, Preferences=retained)
        target = self.root / 'policies.json'
        target.write_text(json.dumps(document))
        receipt = stage.adapt_firefox(target)
        policies = json.loads(target.read_text())['policies']
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(set(policies), set(document['policies']))
        self.assertEqual(policies['ExtensionSettings'], extensions)
        self.assertEqual(policies['Homepage'], homepage)
        for name, entry in retained.items():
            self.assertEqual(policies['Preferences'][name], entry)
        expected = {
            'dom.ipc.processPrelaunch.enabled': False,
            'dom.ipc.processCount': 2,
            'dom.ipc.processCount.webIsolated': 1,
            'browser.newtab.preload': False,
            'browser.aboutwelcome.enabled': False,
            'browser.startup.page': 0,
            'browser.newtabpage.enabled': False,
        }
        defaults = {name: entry for name, entry in policies['Preferences'].items() if name not in retained}
        self.assertEqual(set(defaults), set(expected))
        for name, value in expected.items():
            self.assertEqual(defaults[name], {
                'Value': value, 'Status': 'default',
                'Type': 'boolean' if type(value) is bool else 'number',
            })
        self.assertEqual(receipt['preferences'], defaults)
        self.assertEqual(receipt['policy_sha256'], digest(target.read_bytes()))
        self.assertEqual(receipt['defaults_sha256'], digest((PROFILE / 'firefox-defaults.json').read_bytes()))

    def test_firefox_rejects_malformed_policy_objects_before_writing(self):
        target = self.root / 'policies.json'
        for document in ({}, {'policies': []}, {'policies': None},
                         {'policies': {'Preferences': []}}):
            with self.subTest(document=document):
                original = json.dumps(document).encode()
                target.write_bytes(original)
                with self.assertRaises(ValueError):
                    stage.adapt_firefox(target)
                self.assertEqual(target.read_bytes(), original)

    def bridge_fixture(self, name='payload'):
        payload = self.root / name
        originals = {}
        for relative in ('shell/shell.qml', 'shell/services/PluginShellApi.qml'):
            source = PROJECT / 'desktop/shell' / relative
            originals[relative] = source.read_bytes()
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(originals[relative])
        return payload, originals

    def test_keyboard_bridge_scopes_both_facades_and_preserves_shared_sources(self):
        payload, originals = self.bridge_fixture()
        receipt = stage.adapt_keyboard_bridge(payload)
        self.assertEqual(receipt['entry'], 'omarchy.network')
        self.assertEqual(receipt['surface'], 'read-only keyboardVisible')
        self.assertEqual(set(receipt['files']), set(originals))
        for relative, original in originals.items():
            self.assertEqual((PROJECT / 'desktop/shell' / relative).read_bytes(), original)
            copied = (payload / relative).read_bytes()
            self.assertNotEqual(copied, original)
            self.assertEqual(receipt['files'][relative], digest(copied))
        api = (payload / 'shell/services/PluginShellApi.qml').read_text()
        self.assertIn('readonly property bool keyboardVisible:', api)
        shell = (payload / 'shell/shell.qml').read_text()
        callbacks = re.findall(r'_keyboardVisibleLookup:\s*function\(\)\s*\{(.*?)\n\s*\}',
                               shell, flags=re.DOTALL)
        self.assertEqual(len(callbacks), 2)
        for identifier, body in zip(('key', 'target'), callbacks):
            self.assertIn('currentManifest()', body)
            self.assertIn(identifier + ' === "omarchy.network"', body)
            self.assertIn('entry && entry.__isFirstParty && shell.keyboardVisible', body)
            self.assertIn('return !!(', body)

    def test_keyboard_bridge_rejects_missing_anchors_before_writing_either_file(self):
        for index, (relative, anchor) in enumerate((
            ('shell/services/PluginShellApi.qml', '  property var _serviceLookup: null\n'),
            ('shell/shell.qml', '      pluginId: key,\n      appLibrary:'),
            ('shell/shell.qml', '      pluginId: target,\n      barConfig:'),
        )):
            with self.subTest(anchor=anchor):
                payload, originals = self.bridge_fixture('broken-' + str(index))
                changed = payload / relative
                changed.write_text(changed.read_text().replace(anchor, '', 1))
                before = {name: (payload / name).read_bytes() for name in originals}
                with self.assertRaisesRegex(ValueError, 'facade changed'):
                    stage.adapt_keyboard_bridge(payload)
                self.assertEqual({name: (payload / name).read_bytes() for name in originals}, before)
                for name, original in originals.items():
                    self.assertEqual((PROJECT / 'desktop/shell' / name).read_bytes(), original)

    @unittest.skipUnless(shutil.which('node'), 'node is required to exercise the facade callbacks')
    def test_keyboard_bridge_callbacks_gate_builtin_identity_and_visible_state(self):
        payload, _ = self.bridge_fixture()
        stage.adapt_keyboard_bridge(payload)
        callbacks = re.findall(r'_keyboardVisibleLookup:\s*function\(\)\s*\{(.*?)\n\s*\}',
                               (payload / 'shell/shell.qml').read_text(), flags=re.DOTALL)
        script = r'''
const assert = require('node:assert/strict');
const callbacks = JSON.parse(process.argv[1]);
assert.equal(callbacks.length, 2);
for (const [index, body] of callbacks.entries()) {
  const lookup = new Function('key', 'target', 'currentManifest', 'shell', body);
  for (const id of ['omarchy.network', 'omarchy.network.clone', 'other.plugin']) {
    for (const entry of [null, {}, {__isFirstParty: false}, {__isFirstParty: true}]) {
      for (const visible of [false, true]) {
        const key = index === 0 ? id : 'other.plugin';
        const target = index === 1 ? id : 'other.plugin';
        const result = lookup(key, target, () => entry, {keyboardVisible: visible});
        assert.equal(typeof result, 'boolean');
        assert.equal(result, id === 'omarchy.network' && entry?.__isFirstParty === true && visible);
      }
    }
  }
}
'''
        result = subprocess.run(['node', '-e', script, json.dumps(callbacks)],
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipIf(os.geteuid() == 0 and platform.machine() == 'armv7l',
                     'this case exercises refusal outside the supported build environment')
    def test_prepare_root_refuses_the_host_before_creating_output(self):
        destination = self.root / 'snapshot'
        env = dict(os.environ)
        env.pop('BASH_ENV', None)
        # A missing package file also prevents writes if the host guard regresses.
        result = subprocess.run(['bash', str(PREPARE), '--snapshot', str(destination),
                                 '--packages', str(self.root / 'missing-packages')],
                                env=env, text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Requires root inside an ARMv7', result.stderr)
        self.assertFalse(destination.exists())

    def test_preparation_policy_keeps_kernel_and_signature_guards_before_writes(self):
        source = PREPARE.read_text()
        preflight = source.split('install -d "$snapshot/cache"', 1)[0]
        self.assertIn('$EUID == 0', preflight)
        self.assertIn('/run/.containerenv', preflight)
        self.assertIn('Cascadia supplies the kernel', preflight)
        self.assertIn('linux-armv7*', preflight)
        self.assertIn('linux-aarch64*', preflight)
        configuration = source.split("<<'PACMAN'\n", 1)[1].split('\nPACMAN', 1)[0]
        options = dict(line.split(' = ', 1) for line in configuration.splitlines() if ' = ' in line)
        self.assertEqual(options['SigLevel'], 'Required DatabaseOptional')
        self.assertEqual(options['LocalFileSigLevel'], 'Required')
        self.assertEqual(options['RemoteFileSigLevel'], 'Required')
        self.assertIn('linux-armv7', options['IgnorePkg'].split())
        requested = (PROJECT / 'system/p105/packages.txt').read_text().splitlines()
        packages = {line.split('#', 1)[0].strip() for line in requested}
        self.assertFalse(packages & {'linux', 'linux-armv7', 'linux-aarch64'})
