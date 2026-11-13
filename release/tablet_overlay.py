"""Stage one reviewable v0.2.0 tablet upgrade, without accessing a device."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from release.common import PROJECT
from release.public_root import desktop_additions, desktop_replacements, system_files


def digest(data):
    return hashlib.sha256(data).hexdigest()



WARM_UNITS = ('orchard-kexec-provenance.service', 'orchard-kexec-load.service',
              'orchard-kexec-refresh.service', 'orchard-kexec-refresh.path',
              'orchard-kexec-health.service')
WARM_REQUIRED = {
    'usr/bin/orchard-kexec', 'usr/bin/orchard-restart',
    'usr/lib/orchard-kexec/cli.py', 'usr/lib/orchard-kexec/device.py',
    'usr/lib/orchard-kexec/reset.py', 'usr/lib/orchard-kexec/fdt-merge',
    'usr/lib/orchard-kexec/quiesce-gpu',
    'etc/polkit-1/rules.d/61-orchard-kexec.rules',
    'usr/share/libalpm/hooks/95-orchard-kexec.hook',
    'usr/lib/systemd/system/systemd-kexec.service.d/50-orchard-warm.conf',
    'usr/lib/systemd/system/systemd-reboot.service.d/50-orchard-cold.conf',
    *('usr/lib/systemd/system/'+name for name in WARM_UNITS),
}

def warm_file(name):
    return name in WARM_REQUIRED or name.startswith((
        'usr/lib/orchard-kexec/', 'usr/lib/systemd/system/orchard-kexec-'))


BASE_SHELL=PROJECT/'release/v0.2.0-desktop-shell.tree'


def ls_tree(lines):
    """{path: (mode, object)} from `git ls-tree -r` lines; '#' lines are comments."""
    entries={}
    for line in lines:
        if not line or line.startswith('#'): continue
        meta,path=line.split('\t',1)
        mode,_,oid=meta.split()
        entries[path]=(mode,oid)
    return entries


def changed_since_base():
    """desktop/shell paths that differ between v0.2.0 and HEAD, as
    `git diff --name-only v0.2.0 HEAD -- desktop/shell` lists them, but against
    the recorded v0.2.0 tree: a shallow checkout without tags (CI) has HEAD's
    tree, not the tag."""
    base=ls_tree(BASE_SHELL.read_text().splitlines())
    head=ls_tree(subprocess.check_output(['git','ls-tree','-r','HEAD','--','desktop/shell'],
                                         cwd=PROJECT,text=True).splitlines())
    return sorted(name for name in base.keys()|head.keys() if base.get(name)!=head.get(name))


def stage(output, package):
    if output.exists():
        raise ValueError('Choose a nonexistent output directory')
    files=system_files()
    prefix='home/tablet/.local/share/omarchy-ipad/'
    for name,data in desktop_replacements().items():
        files[name]=(data,0o755 if '/bin/' in name or name.endswith('/autostart') or '/libexec/' in name else 0o644)
    files.update(desktop_additions())
    # Upgrade the complete native picker/Bluetooth/charging path from v0.2.0,
    # rather than staging a new caller against an old IPC implementation.
    changed=changed_since_base()
    changed += ['desktop/shell/shell/Commons/Style.qml','desktop/shell/shell/Ui/ScreenMoveRemap.qml',
                'desktop/shell/shell/plugins/services/idle/Service.qml','desktop/shell/bin/omarchy-keyboard']
    removed = ['home/tablet/.local/share/omarchy-ipad/bin/omarchy-tablet-power', 'usr/local/bin/omarchy-tablet-power']
    for name in changed:
        if name == 'desktop/shell/bin/omarchy-tablet-power': continue  # superseded by powerd
        path=PROJECT/name
        if not path.is_file(): raise ValueError('Removed desktop file needs an explicit migration: '+name)
        rel=path.relative_to(PROJECT/'desktop/shell').as_posix()
        files[prefix+rel]=(path.read_bytes(),0o755 if rel.startswith('bin/') else 0o644)
    # Both symlinked old commands and newly introduced commands work after apply.
    for name,(data,mode) in list(files.items()):
        if name.startswith(prefix+'bin/'):
            files['usr/local/bin/'+Path(name).name]=(data,mode)
    files['usr/local/libexec/arch-ipad-touch-output']=((PROJECT/'desktop/configuration/touch-output').read_bytes(),0o755)
    files['usr/local/libexec/arch-ipad-login-session']=((PROJECT/'desktop/configuration/login-session').read_bytes(),0o755)
    # Do not replace identity, PAM, sudo, networking or installer policy as a side
    # effect of the desktop port. Those belong to the installed release.
    files={name:value for name,value in files.items() if warm_file(name) or not name.startswith((
        'etc/os-release','etc/pam.d/','etc/sudoers.d/','etc/NetworkManager/','etc/orchard/',
        'etc/polkit-1/','usr/libexec/orchard-','usr/lib/systemd/system/orchard-',
        'usr/lib/systemd/system/omarchy-pacman-init','usr/lib/tmpfiles.d/omarchy-greeter'))}
    missing = WARM_REQUIRED - files.keys()
    if missing:
        raise ValueError('Incomplete warm restart stack: '+', '.join(sorted(missing)))
    menu = prefix+'default/omarchy/omarchy-menu.jsonc'
    disabled_menu = 'packages/menu-without-kexec.jsonc'
    menu_data, menu_mode = files[menu]
    if b'"action":"orchard-restart"' not in menu_data:
        raise ValueError('Restart menu action changed; update both variants')
    files[disabled_menu] = (menu_data.replace(b'"action":"orchard-restart"',
                                             b'"action":"systemctl reboot"'), menu_mode)
    warm_paths = sorted(name for name in files if warm_file(name))
    files['packages/wlroots0.20.pkg.tar.xz']=(package.read_bytes(),0o644)
    files['packages/wlroots0.20.PKGBUILD']=((PROJECT/'desktop/packages/wlroots0.20/PKGBUILD').read_bytes(),0o644)
    for path in (PROJECT/'desktop/packages/wlroots0.20').glob('*.patch'):
        files['packages/'+path.name]=(path.read_bytes(),0o644)
    output.mkdir(parents=True)
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip()
    manifest={'schema':1,'head':head,'base':'omarchy-a-v0.2.0','files':{},
              'packages':['iio-sensor-proxy','udiskie','udisks2'],
              'warm_restart': {'files':warm_paths,'units':list(WARM_UNITS),
                               'menu':menu,'disabled_menu':disabled_menu},
              'remove': removed, 'new_login':True,'reboot':['zram size','logind cover policy','systemd boot status'],
              'gpu':'No GPU bundle or Mesa: renderer chosen by session launcher.'}
    with tarfile.open(output/'overlay.tar.gz','w:gz') as archive:
        for name,(data,mode) in sorted(files.items()):
            uid=1000 if name.startswith('home/tablet/') else 0
            info=tarfile.TarInfo(name); info.size=len(data); info.mode=mode;info.uid=info.gid=uid;info.mtime=0
            archive.addfile(info,io.BytesIO(data))
            manifest['files'][name]={'sha256':digest(data),'mode':mode,'uid':uid,'gid':uid}
    manifest['archive_sha256']=digest((output/'overlay.tar.gz').read_bytes())
    apply=(PROJECT/'release/apply_tablet_overlay.py').read_bytes()
    (output/'apply.py').write_bytes(apply)
    manifest['apply_sha256']=digest(apply)
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    (output/'SHA256SUMS').write_text(''.join(digest((output/name).read_bytes())+'  '+name+'\n' for name in ('overlay.tar.gz','manifest.json','apply.py')))
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output',type=Path);ap.add_argument('--wlroots-package',required=True,type=Path)
    a=ap.parse_args(); m=stage(a.output,a.wlroots_package)
    print(f'Staged {len(m["files"])} files from {m["head"]} in {a.output}')

if __name__=='__main__': main()
