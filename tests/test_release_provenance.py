"""Assembly provenance measures the source and component bytes it records."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from release.provenance import component_receipt, source_identity, orchard_identity, input_revision
from release import provenance


class Provenance(unittest.TestCase):
    def test_component_manifest_digest_cannot_hide_changed_member_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            member = root / 'helper'
            member.write_bytes(b'original')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'schema': 1, 'files': {
                'helper': hashlib.sha256(member.read_bytes()).hexdigest()}}))
            record = component_receipt(root)
            self.assertEqual(record['manifest']['sha256'], hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(record['files']['helper']['bytes'], 8)
            member.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'differs from manifest'):
                component_receipt(root)

    def test_unversioned_source_snapshot_records_exact_tree_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'recipe.py').write_text('first version\n')
            first = source_identity(root)
            (root / 'recipe.py').write_text('second version\n')
            second = source_identity(root)
            self.assertIsNone(first['commit'])
            self.assertEqual(first['files'], 1)
            self.assertNotEqual(first['tree_sha256'], second['tree_sha256'])

    def test_orchard_source_archive_keeps_null_revision_and_exact_tree_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            subprocess.run(['git', 'init', '-q', str(parent)], check=True)
            (parent / '.gitignore').write_text('out/\n')
            root = parent / 'out/archive'
            (root / 'src/orchard').mkdir(parents=True)
            source = root / 'src/orchard/buildenv.py'
            source.write_text('source archive version one\n')
            # An archive inside another checkout must keep its own unversioned identity.
            with patch.object(provenance.snapshot, 'revision', side_effect=AssertionError('parent Git inherited')):
                initial = orchard_identity(root)
            self.assertEqual(input_revision(initial, {'commit': None, 'modified': None}),
                             {'commit': None, 'modified': None})
            self.assertEqual(len(initial['tree_sha256']), 64)
            self.assertEqual(initial['files'], 1)
            with self.assertRaisesRegex(ValueError, 'matching null/null'):
                input_revision(initial)
            with self.assertRaisesRegex(ValueError, 'inputs revision differs'):
                input_revision(initial, {'commit': 'a' * 40, 'modified': False})
            source.write_text('source archive version two\n')
            self.assertNotEqual(orchard_identity(root)['tree_sha256'], initial['tree_sha256'])

    def test_dirty_orchard_git_source_remains_rejected(self):
        dirty = {'commit': 'a' * 40, 'modified': True, 'tree_sha256': 'b' * 64, 'files': 1}
        with patch.object(provenance, 'source_identity', return_value=dirty), \
                self.assertRaisesRegex(ValueError, 'clean Orchard'):
            orchard_identity(Path('/source'))


if __name__ == '__main__':
    unittest.main()
