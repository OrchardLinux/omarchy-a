"""Audit the finished public P105 root and its compatibility receipt."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import tarfile

FORBIDDEN = {
    'lib/firmware/mtcal.bin', 'usr/lib/firmware/mtcal.bin',
    'usr/lib/firmware/P105.mtprops', 'usr/lib/firmware/apple/sgx543.fw',
    'usr/lib/firmware/brcm/brcmfmac4334.bin', 'usr/lib/firmware/brcm/BCM4334B0.hcd',
    'etc/orchard/p105.json', 'root/.ssh/authorized_keys',
}


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def name(value):
    path=PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Unsafe P105 root path: '+value)
    return str(path)


def inventory(path):
    catalog={}
    captured={}
    wanted={'etc/passwd','etc/shadow','etc/machine-id','etc/cascadia/systemd-root',
            'etc/cascadia/p105-hardware-input.json','etc/sudoers.d/90-tablet-passwordless',
            'home/tablet/.config/labwc/autostart','home/tablet/.config/labwc/rc.xml',
            'usr/local/libexec/arch-ipad-login-session'}
    with tarfile.open(path,'r:gz') as archive:
        for member in archive:
            key=name(member.name)
            if key in catalog:
                raise ValueError('Duplicate P105 root member: '+key)
            if member.islnk() or not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError('Unsupported P105 root member: '+key)
            if (key in FORBIDDEN or key.startswith(('root/.ssh/','home/tablet/.ssh/',
                    'etc/NetworkManager/system-connections/')) or
                    key.startswith('etc/ssh/ssh_host_')):
                if not member.isdir():
                    raise ValueError('Private input in public P105 root: '+key)
            item={'mode':member.mode,'uid':member.uid,'gid':member.gid}
            if member.isdir():
                item['type']='directory'
            elif member.issym():
                target=member.linkname
                resolved=posixpath.normpath(target.lstrip('/') if target.startswith('/') else
                                            posixpath.join(posixpath.dirname(key),target))
                if resolved=='..' or resolved.startswith('../'):
                    raise ValueError('Root symlink escapes the guest: '+key)
                item.update(type='symlink',target=target)
            else:
                digest=hashlib.sha256()
                head=b''
                tail=b''
                saved=bytearray()
                with archive.extractfile(member) as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):
                        digest.update(block)
                        if not head:
                            head=block[:52]
                        window=tail+block
                        # Signed programs such as gnutls-cli embed public test
                        # keys. Credential files are checked as text here;
                        # owner-specific bytes receive a separate build audit.
                        if not head.startswith(b'\x7fELF') and re.search(rb'-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP) PRIVATE KEY(?: BLOCK)?-----[\r\n]+[A-Za-z0-9+/=\r\n]{64,}',window):
                            raise ValueError('Private key in public P105 root: '+key)
                        tail=window[-128:]
                        if key in wanted:
                            if len(saved)+len(block)>1024*1024:
                                raise ValueError('Oversized P105 policy file: '+key)
                            saved.extend(block)
                if head.startswith(b'\x7fELF'):
                    arm32=head[:7]==b'\x7fELF\x01\x01\x01' and head[18:20]==b'\x28\x00'
                    # v4l-utils supplies architecture-independent eBPF objects
                    # for its remote-control protocols.
                    bpf=head[:7]==b'\x7fELF\x02\x01\x01' and head[16:20]==b'\x01\x00\xf7\x00'
                    if not (arm32 or bpf):
                        raise ValueError('Non-ARM32 ELF in P105 root: '+key)
                item.update(type='file',bytes=member.size,sha256=digest.hexdigest())
                if key in wanted:
                    captured[key]=bytes(saved)
            catalog[key]=item
    return catalog,captured


def audit(directory):
    directory=Path(directory)
    root=json.loads((directory/'rootfs.json').read_text())
    if (root.get('kind'),root.get('profile'),root.get('architecture'))!=('omarchy-a.nfs-root','p105','armv7h'):
        raise ValueError('Expected a P105 ARMv7 NFS root receipt')
    asset=root['root']
    if asset['file']!='rootfs.tar.gz' or asset['compression']!='gzip':
        raise ValueError('Unexpected P105 root stream')
    path=directory/asset['file']
    if path.stat().st_size!=asset['bytes'] or sha(path)!=asset['sha256']:
        raise ValueError('P105 root differs from its receipt')
    catalog,files=inventory(path)
    expected=json.loads((directory/'rootfs.catalog.json').read_text())
    if catalog!=expected or sha(directory/'rootfs.catalog.json')!=root['catalog_sha256']:
        raise ValueError('P105 root inventory differs from its receipt')
    if len(catalog)!=asset['members'] or sum(v.get('bytes',0) for v in catalog.values())!=asset['expanded_bytes']:
        raise ValueError('P105 root dimensions differ')
    if files.get('etc/cascadia/systemd-root')!=b'p105-systemd-v1\n' or files.get('etc/machine-id')!=b'':
        raise ValueError('P105 root has incompatible hardware policy or machine identity')
    if not any(row.startswith(b'tablet:x:1000:1000:') for row in files['etc/passwd'].splitlines()):
        raise ValueError('P105 root needs the tablet account at UID 1000')
    sudo=catalog.get('usr/bin/sudo',{})
    if sudo.get('uid')!=0 or sudo.get('mode',0)&0o4777!=0o4755:
        raise ValueError('P105 root must retain the package sudo owner and mode')
    if catalog.get('etc/sudoers.d/90-tablet-passwordless',{}).get('mode')!=0o440:
        raise ValueError('P105 sudo policy mode differs')
    if any(row.split(b':')[1].strip(b'!*') for row in files['etc/shadow'].splitlines() if row):
        raise ValueError('Password material in public P105 root')
    if b'WLR_RENDERER=pixman QT_QUICK_BACKEND=software' not in files['usr/local/libexec/arch-ipad-login-session']:
        raise ValueError('P105 software rendering policy differs')
    hardware=json.loads(files['etc/cascadia/p105-hardware-input.json'])
    for key,digest in hardware['files'].items():
        if catalog.get(key,{}).get('sha256')!=digest:
            raise ValueError('P105 hardware runtime differs: '+key)
    if root['compatibility']['runtime']!='p105-systemd-v1' or root['compatibility']['flash_controller']!='disabled':
        raise ValueError('P105 compatibility fence differs')
    print('Verified public P105 ARMv7 NFS root:',directory)
    return root


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    audit(args.directory)


if __name__=='__main__':
    main()
