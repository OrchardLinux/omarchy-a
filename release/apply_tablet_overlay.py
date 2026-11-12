#!/usr/bin/env python3
"""Verify and apply a tablet overlay. Default is a read-only plan; no implicit logout/reboot.

--root DIR stages files in a host fixture, without package operations or service
activation. On a live root, --apply needs root and signed distro dependencies.
All replaced payload files, package files and its pacman database are backed up.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time


def sha(data): return hashlib.sha256(data).hexdigest()


def safe(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path)!=name or not path.parts:
        raise ValueError('Unsafe path: '+name)
    return name


def verified(bundle):
    manifest=json.loads((bundle/'manifest.json').read_text())
    if manifest['schema']!=1: raise ValueError('Unknown overlay schema')
    if sha((bundle/'apply.py').read_bytes())!=manifest['apply_sha256']:
        raise ValueError('Apply script hash mismatch')
    raw=(bundle/'overlay.tar.gz').read_bytes()
    if sha(raw)!=manifest['archive_sha256']: raise ValueError('Archive hash mismatch')
    files={}
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        for member in archive:
            name=safe(member.name)
            if name in files or not member.isfile() or name not in manifest['files']:
                raise ValueError('Unexpected/duplicate archive member: '+name)
            data=archive.extractfile(member).read(); expected=manifest['files'][name]
            if sha(data)!=expected['sha256'] or member.mode!=expected['mode'] or member.uid!=expected['uid'] or member.gid!=expected['gid']:
                raise ValueError('Payload hash/metadata mismatch: '+name)
            files[name]=data
    if files.keys()!=manifest['files'].keys(): raise ValueError('Incomplete payload')
    return manifest,files


def parents_safe(root,name):
    path=root/safe(name)
    for parent in path.parents:
        if parent==root: break
        if parent.is_symlink(): raise ValueError('Symlink parent: '+str(parent))
        if parent.exists() and not parent.is_dir(): raise ValueError('Non-directory parent: '+str(parent))
    if path.exists() and not path.is_file() and not path.is_symlink():
        raise ValueError('Not a regular file: '+str(path))
    return path


def backup_file(root,backup,name,record):
    if name in record: return
    path=parents_safe(root,name)
    existed=path.exists() or path.is_symlink()
    record[name]={'existed':existed}
    if existed:
        target=backup/'files'/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target,follow_symlinks=False)
        info=path.lstat()
        record[name].update(uid=info.st_uid,gid=info.st_gid,mode=stat.S_IMODE(info.st_mode))


def target_warm_supported(root):
    helper=root/'usr/lib/orchard/device-feature'
    try:
        return helper.is_file() and subprocess.run(
            [str(helper),'warm_restart','working'],check=False,timeout=10,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0
    except (OSError,subprocess.SubprocessError):
        return False


def select_restart_stack(root,manifest,files):
    # Keep the signed archive intact; record the effective target-specific plan.
    manifest=json.loads(json.dumps(manifest));files=dict(files)
    warm=target_warm_supported(root)
    policy=manifest['warm_restart']
    manifest['warm_restart']['selected']='complete' if warm else 'none'
    if not warm:
        for name in policy['files']:
            files.pop(name)
            manifest['files'].pop(name)
            manifest['remove'].append(name)
        name=policy['menu'];data=files[policy['disabled_menu']]
        files[name]=data
        manifest['files'][name]['sha256']=sha(data)
    return manifest,files


def apply(bundle,root,write=False):
    root=root.resolve(); manifest,files=verified(bundle)
    manifest,files=select_restart_stack(root,manifest,files)
    live=root==Path('/')
    for name in [*files, *manifest['remove']]:
        if not name.startswith('packages/'): parents_safe(root,name)
    if live and write and os.geteuid()!=0: raise ValueError('Live apply requires root')
    print(json.dumps({'head':manifest['head'],'apply':write,'live':live,'files':len(files),
                      'packages':manifest['packages'],'warm_restart':manifest['warm_restart']['selected'],'new_login':True,'reboot':manifest['reboot']}))
    if not write: return
    backup=root/'var/lib/omarchy-a/port-backups'/time.strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True,exist_ok=False)
    record={}
    for name in [*files, *manifest['remove']]:
        if not name.startswith('packages/'): backup_file(root,backup,name,record)
    def receipt():
        (backup/'backup.json').write_text(json.dumps(record,indent=2)+'\n')
        (backup/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    receipt()  # persisted before first mutation, including failed package installs
    with tempfile.TemporaryDirectory(prefix='tablet-port-',dir=backup) as temp:
        pkg=Path(temp)/'wlroots0.20.pkg.tar.xz'; pkg.write_bytes(files['packages/wlroots0.20.pkg.tar.xz'])
        if live:
            old=subprocess.check_output(['pacman','-Q'],text=True)
            (backup/'packages.before').write_text(old)
            # Back up every file replaced by pacman's local wlroots package.
            names=subprocess.check_output(['pacman','-Qlq','wlroots0.20'],text=True).splitlines()
            for name in names:
                if name.endswith('/'): continue
                backup_file(root,backup,name.lstrip('/'),record)
            for db in (root/'var/lib/pacman/local').glob('wlroots0.20-*'):
                shutil.copytree(db,backup/db.name,symlinks=True)
            receipt()
            # No -Sy: use the installed distribution snapshot. A stale DB failure
            # stops here, before replacing desktop files; never force dependencies.
            missing=[name for name in manifest['packages'] if subprocess.run(['pacman','-Q',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode]
            if missing: subprocess.run(['pacman','-S','--needed','--noconfirm',*missing],check=True)
            subprocess.run(['pacman','-U','--needed','--noconfirm',str(pkg)],check=True)
            with tarfile.open(pkg, 'r:xz') as archive:
                for member in archive:
                    if member.isfile() and member.name.startswith('usr/'):
                        path=parents_safe(root,member.name)
                        if sha(path.read_bytes())!=sha(archive.extractfile(member).read()):
                            raise ValueError('Installed package hash mismatch: '+member.name)
        for name,data in files.items():
            if name.startswith('packages/'): continue
            path=parents_safe(root,name);path.parent.mkdir(parents=True,exist_ok=True)
            expected=manifest['files'][name]
            fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.tablet-port-')
            try:
                with os.fdopen(fd,'wb') as stream: stream.write(data)
                os.chmod(tmp,expected['mode'])
                if live: os.chown(tmp,expected['uid'],expected['gid'])
                os.replace(tmp,path)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
            if sha(path.read_bytes())!=expected['sha256']: raise ValueError('Installed hash mismatch: '+name)
        for name in manifest['remove']:
            parents_safe(root,name).unlink(missing_ok=True)
        if live:
            subprocess.run(['systemctl','daemon-reload'],check=True)
            subprocess.run(['systemd-tmpfiles','--create','/usr/lib/tmpfiles.d/omarchy-a-memory.conf'],check=True)
            subprocess.run(['sysctl','-p','/etc/sysctl.d/90-omarchy-a-memory.conf'],check=True)
            subprocess.run(['udevadm','control','--reload'],check=True)
            subprocess.run(['udevadm','trigger','--subsystem-match=input'],check=True)
            subprocess.run(['systemctl','enable','omarchy-powerd.service','omarchy-usb-recover.service','omarchy-bluetooth-connectable.service','omarchy-bluetooth-connectable.timer'],check=True)
            if manifest['warm_restart']['selected']=='complete':
                subprocess.run(['systemctl','enable',*manifest['warm_restart']['units']],check=True)
            subprocess.run(['systemctl','restart','omarchy-powerd.service'],check=True)
            subprocess.run(['systemctl','start','omarchy-usb-recover.service','omarchy-bluetooth-connectable.service','omarchy-bluetooth-connectable.timer'],check=True)
    (backup/'APPLIED').write_text(manifest['head']+'\n')
    print('Verified installed files. Backup: '+str(backup))
    print('Log out and log in for desktop/wlroots/touch/input changes. Reboot for zram size and logind policy. No logout/reboot performed.')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path('/'))
    ap.add_argument('--apply',action='store_true')
    a=ap.parse_args(); apply(Path(__file__).resolve().parent,a.root,a.apply)

if __name__=='__main__': main()
