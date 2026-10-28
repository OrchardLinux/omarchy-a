"""P105 public-root boundaries using disposable archives."""
import io
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

from release.p105 import audit


class P105Release(unittest.TestCase):
    def archive(self, root, entries):
        archive=root/'root.tar.gz'
        with tarfile.open(archive,'w:gz') as stream:
            for name,kind,value in entries:
                member=tarfile.TarInfo(name)
                if kind=='file':
                    member.size=len(value)
                    stream.addfile(member,io.BytesIO(value))
                else:
                    member.type=kind
                    if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):member.linkname=value
                    stream.addfile(member)
        return archive

    def rejects(self, entries, message):
        with tempfile.TemporaryDirectory() as temporary:
            path=self.archive(Path(temporary),entries)
            with self.assertRaisesRegex(ValueError,message):audit.inventory(path)

    def test_member_traversal_is_rejected(self):
        for name in ('../outside','/etc/outside','usr/../../outside'):
            with self.subTest(name=name):self.rejects([(name,'file',b'x')],'Unsafe')

    def test_link_traversal_and_special_members_are_rejected(self):
        self.rejects([('usr/link',tarfile.SYMTYPE,'../../outside')],'escapes')
        self.rejects([('dev/disk',tarfile.CHRTYPE,'')],'Unsupported')
        self.rejects([('usr/hard',tarfile.LNKTYPE,'usr/file')],'Unsupported')

    def test_duplicate_normalized_paths_are_rejected(self):
        self.rejects([('./etc/value','file',b'a'),('etc/value','file',b'b')],'Duplicate')

    def test_owner_inputs_are_rejected(self):
        for name in ('etc/ssh/ssh_host_ed25519_key','home/tablet/.ssh/authorized_keys',
                     'usr/lib/firmware/mtcal.bin','etc/orchard/p105.json',
                     'etc/NetworkManager/system-connections/owner.nmconnection'):
            with self.subTest(name=name):self.rejects([(name,'file',b'private input')],'Private input')

    def test_private_key_body_is_rejected(self):
        key=b'-----BEGIN OPENSSH PRIVATE KEY-----\n'+b'A'*80+b'\n'
        self.rejects([('unexpected/key','file',key)],'Private key')

    def test_documented_key_header_is_ordinary_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self.archive(Path(temporary),[('usr/lib/parser.py','file',b'header = "-----BEGIN OPENSSH PRIVATE KEY-----"\n')])
            catalog,_=audit.inventory(path)
            self.assertEqual(catalog['usr/lib/parser.py']['type'],'file')

    def test_non_arm_executable_is_rejected(self):
        header=bytearray(52);header[:7]=b'\x7fELF\x02\x01\x01';struct.pack_into('<H',header,18,183)
        self.rejects([('usr/bin/program','file',bytes(header))],'Non-ARM32')

    def test_arm_program_can_contain_its_upstream_public_test_key(self):
        header=bytearray(52);header[:7]=b'\x7fELF\x01\x01\x01';struct.pack_into('<H',header,18,40)
        data=bytes(header)+b'-----BEGIN RSA PRIVATE KEY-----\n'+b'A'*80+b'\n'
        with tempfile.TemporaryDirectory() as temporary:
            path=self.archive(Path(temporary),[('usr/bin/tls-test','file',data)])
            catalog,_=audit.inventory(path)
            self.assertEqual(catalog['usr/bin/tls-test']['bytes'],len(data))

    def test_architecture_independent_bpf_object_is_accepted(self):
        header=bytearray(52);header[:7]=b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HH',header,16,1,247)
        with tempfile.TemporaryDirectory() as temporary:
            path=self.archive(Path(temporary),[('usr/lib/udev/protocol.o','file',bytes(header))])
            catalog,_=audit.inventory(path)
            self.assertIn('usr/lib/udev/protocol.o',catalog)

    def test_guest_absolute_links_keep_their_guest_meaning(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self.archive(Path(temporary),[('usr/local/bin/app',tarfile.SYMTYPE,'/home/tablet/app')])
            catalog,_=audit.inventory(path)
            self.assertEqual(catalog['usr/local/bin/app']['target'],'/home/tablet/app')


if __name__=='__main__':
    unittest.main()
