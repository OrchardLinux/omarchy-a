"""Private P105 staging preserves guest paths and rejects unrelated owner files."""
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest

from release.p105 import prepare_nfs


class P105NFS(unittest.TestCase):
    def test_absolute_guest_link_is_staged_as_equivalent_relative_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'root';root.mkdir();archive=base/'root.tar.gz'
            with tarfile.open(archive,'w:gz') as stream:
                m=tarfile.TarInfo('usr/local/bin/app');m.type=tarfile.SYMTYPE
                m.linkname='/home/tablet/app';m.uid=os.getuid();m.gid=os.getgid();stream.addfile(m)
            prepare_nfs.extract(archive,root)
            link=root/'usr/local/bin/app'
            self.assertEqual(link.resolve(),root.resolve()/'home/tablet/app')
            self.assertFalse(os.readlink(link).startswith('/'))

    def test_extraction_refuses_an_outside_parent_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'root';root.mkdir();outside=base/'outside';outside.mkdir()
            (root/'etc').symlink_to(outside,target_is_directory=True)
            archive=base/'root.tar.gz'
            with tarfile.open(archive,'w:gz') as stream:
                m=tarfile.TarInfo('etc/file');m.size=1;stream.addfile(m,io.BytesIO(b'x'))
            with self.assertRaisesRegex(ValueError,'parent escapes'):
                prepare_nfs.extract(archive,root)
            self.assertEqual(list(outside.iterdir()),[])

    def record(self,root,key,data=b'owner key'):
        path=root/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        record={'schema':1,'profile':'p105','files':{key:hashlib.sha256(data).hexdigest()}}
        (root/'owner-inputs.json').write_text(json.dumps(record))

    def test_owner_profile_accepts_an_integrity_checked_tablet_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);key='home/tablet/.ssh/authorized_keys';self.record(root,key)
            self.assertEqual(list(prepare_nfs.owner_files(root)),[key])
            (root/key).write_text('changed')
            with self.assertRaisesRegex(ValueError,'differs'):
                prepare_nfs.owner_files(root)

    def test_owner_profile_cannot_copy_unrelated_system_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);self.record(root,'etc/sudoers')
            with self.assertRaisesRegex(ValueError,'Unexpected'):
                prepare_nfs.owner_files(root)

    def test_owner_profile_rejects_a_linked_parent(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);root=base/'inputs';root.mkdir();outside=base/'outside';outside.mkdir()
            key='home/tablet/.ssh/authorized_keys';self.record(root,key)
            path=root/'home';path.rename(outside/'home');path.symlink_to(outside/'home')
            with self.assertRaisesRegex(ValueError,'differs'):
                prepare_nfs.owner_files(root)


if __name__=='__main__':
    unittest.main()
