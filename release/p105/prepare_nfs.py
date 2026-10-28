"""Expand an audited P105 root and apply explicit owner inputs for an NFS host."""
import argparse
import json
import os
from pathlib import Path
import posixpath
import shutil
import tarfile

from .audit import audit, name, sha


def extract(archive,root):
    """Keep guest links inside the staging root while preserving numeric owners."""
    with tarfile.open(archive,'r:gz') as stream:
        for member in stream:
            key=name(member.name)
            if key=='.':
                os.chown(root,member.uid,member.gid)
                root.chmod(member.mode)
                continue
            path=root/key
            if not path.parent.resolve().is_relative_to(root.resolve()):
                raise ValueError('Guest extraction parent escapes the root: '+key)
            path.parent.mkdir(parents=True,exist_ok=True)
            if member.isdir():
                if path.is_symlink():
                    raise ValueError('Directory would replace a link: '+key)
                path.mkdir(exist_ok=True)
                os.chown(path,member.uid,member.gid)
                path.chmod(member.mode)
            elif member.issym():
                target=member.linkname
                if target.startswith('/'):
                    target=posixpath.relpath(target.lstrip('/'),posixpath.dirname(key) or '.')
                destination=posixpath.normpath(posixpath.join(posixpath.dirname(key),target))
                if destination=='..' or destination.startswith('../'):
                    raise ValueError('Guest extraction link escapes the root: '+key)
                path.symlink_to(target)
                os.lchown(path,member.uid,member.gid)
            elif member.isfile():
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as output,stream.extractfile(member) as source:
                    shutil.copyfileobj(source,output)
                    os.fchown(output.fileno(),member.uid,member.gid)
                    os.fchmod(output.fileno(),member.mode)
            else:
                raise ValueError('Unsupported guest extraction member')


def owner_files(directory):
    record=json.loads((directory/'owner-inputs.json').read_text())
    if record.get('schema')!=1 or record.get('profile')!='p105':
        raise ValueError('Expected explicit P105 owner inputs')
    allowed={'etc/ssh/ssh_host_ed25519_key','etc/ssh/ssh_host_ed25519_key.pub',
             'home/tablet/.ssh/authorized_keys'}
    files={}
    for key,digest in record['files'].items():
        if name(key)!=key or (key not in allowed and not key.startswith('etc/NetworkManager/system-connections/')):
            raise ValueError('Unexpected private owner input')
        source=directory/key
        if (source.is_symlink() or not source.resolve().is_relative_to(directory.resolve()) or
                not source.is_file() or source.stat().st_size>1024*1024 or sha(source)!=digest):
            raise ValueError('Owner input differs from its receipt')
        files[key]=source
    return files


def prepare(release,destination,owner=None):
    release,destination=Path(release),Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink() or destination==Path('/'):
        raise ValueError('Choose a new private NFS root')
    root=audit(release)
    files=owner_files(Path(owner)) if owner else {}
    if os.geteuid()!=0:
        raise ValueError('NFS staging needs administrator access to preserve guest UID/GID and sudo modes')
    destination.mkdir(parents=True,mode=0o755)
    probe=destination/'.p105-case-probe'
    probe.write_bytes(b'')
    sensitive=not (destination/'.P105-CASE-PROBE').exists()
    probe.unlink()
    if not sensitive:
        destination.rmdir()
        raise ValueError('Stage the Linux root on a case-sensitive filesystem')
    extract(release/'rootfs.tar.gz',destination)
    for key,source in files.items():
        target=destination/key
        if not target.parent.resolve().is_relative_to(destination.resolve()) or target.is_symlink():
            raise ValueError('Owner destination escapes the prepared root')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        tablet=key.startswith('home/tablet/')
        os.chown(target,1000 if tablet else 0,1000 if tablet else 0)
        target.chmod(0o644 if key.endswith('.pub') else 0o600)
        if tablet:
            os.chown(target.parent,1000,1000)
            target.parent.chmod(0o700)
    if 'etc/ssh/ssh_host_ed25519_key' in files:
        config=destination/'etc/ssh/sshd_config.d/10-p105-owner.conf'
        config.parent.mkdir(parents=True,exist_ok=True)
        config.write_text('HostKey /etc/ssh/ssh_host_ed25519_key\nPasswordAuthentication no\n'
                          'KbdInteractiveAuthentication no\nPubkeyAuthentication yes\n'
                          'PermitRootLogin prohibit-password\nAllowUsers root tablet\nUsePAM yes\n')
        config.chmod(0o644)
        wants=destination/'etc/systemd/system/multi-user.target.wants'
        wants.mkdir(parents=True,exist_ok=True)
        (wants/'sshd.service').symlink_to('../../../../usr/lib/systemd/system/sshd.service')
    (destination/'etc/hostname').write_text('p105-omarchy\n')
    (destination/'etc/hosts').write_text('127.0.0.1 localhost\n::1 localhost\n127.0.1.1 p105-omarchy\n')
    result={'schema':1,'private':True,'publishable':False,'profile':'p105','release':root['release'],
            'public_root_sha256':root['root']['sha256'],'owner_files':list(files),
            'link_policy':'guest absolute links normalized to equivalent relative staging links'}
    receipt=destination.parent/(destination.name+'.private.json')
    receipt.write_text(json.dumps(result,indent=2)+'\n');receipt.chmod(0o600)
    print('Prepared private P105 NFS root:',destination)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--owner-inputs',type=Path)
    args=parser.parse_args()
    prepare(args.release,args.destination,args.owner_inputs)


if __name__=='__main__':
    main()
