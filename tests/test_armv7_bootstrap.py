"""Compiler bootstrap verification binds its bytes and signer before import."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]


def producer():
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader('armv7_bootstrap', str(PROJECT / 'system/build-armv7-builder'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BootstrapVerification(unittest.TestCase):
    def fixtures(self, root):
        archive, signature = root / 'root.tar.gz', root / 'root.tar.gz.sig'
        archive.write_bytes(b'archive bytes')
        signature.write_bytes(b'signature bytes')
        pin = {'bytes': archive.stat().st_size,
               'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
               'signature_sha256': hashlib.sha256(signature.read_bytes()).hexdigest(),
               'signer': 'A' * 40}
        return archive, signature, pin

    def test_wrong_archive_or_signature_stops_before_gpg(self):
        module = producer()
        with tempfile.TemporaryDirectory() as directory:
            archive, signature, pin = self.fixtures(Path(directory))
            for target in (archive, signature):
                original = target.read_bytes()
                target.write_bytes(b'changed')
                with self.subTest(target=target.name), patch.object(module.subprocess, 'run') as run, \
                        self.assertRaisesRegex(ValueError, 'pinned|pin'):
                    module.verify(archive, signature, pin)
                run.assert_not_called()
                target.write_bytes(original)

    def test_good_signature_from_another_key_is_refused(self):
        module = producer()
        with tempfile.TemporaryDirectory() as directory:
            archive, signature, pin = self.fixtures(Path(directory))
            with patch.object(module.subprocess, 'run', return_value=types.SimpleNamespace(
                    stdout='[GNUPG:] VALIDSIG ' + 'B' * 40 + ' date\n')):
                with self.assertRaisesRegex(ValueError, 'wrong signer'):
                    module.verify(archive, signature, pin)

    def test_download_bound_removes_partial_file(self):
        module = producer()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'archive'
            with patch.object(module, 'urlopen', return_value=io.BytesIO(bytes(100))), \
                    self.assertRaisesRegex(ValueError, 'size bound'):
                module.fetch('http://example.invalid/archive', target, 99)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.part').exists())

    def test_a_refreshed_upstream_falls_back_to_the_dated_copy_and_back(self):
        module = producer()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'archive'
            served = {'https://copy.invalid/dated': b'pinned build', 'http://upstream.invalid/latest': b'newer build'}
            pinned = hashlib.sha256(b'pinned build').hexdigest()
            with patch.object(module, 'urlopen', side_effect=lambda url, timeout: io.BytesIO(served[url])):
                module.fetch_first(['http://upstream.invalid/latest', 'https://copy.invalid/dated'], target, 100, pinned)
                self.assertEqual(target.read_bytes(), b'pinned build')
                target.unlink()
                with self.assertRaisesRegex(ValueError, 'another build'):
                    module.fetch_first(['http://upstream.invalid/latest'], target, 100, pinned)
            self.assertFalse(target.exists())

    def test_the_pin_names_a_dated_copy_before_upstream_latest(self):
        import json
        pin = json.loads((PROJECT / 'system/armv7/bootstrap.json').read_text())
        self.assertNotIn('latest', pin['urls'][0])
        self.assertIn(pin['build_date'].replace('-', ''), pin['urls'][0])
        self.assertEqual(len(pin['urls']), len(pin['signature_urls']))


if __name__ == '__main__':
    unittest.main()
