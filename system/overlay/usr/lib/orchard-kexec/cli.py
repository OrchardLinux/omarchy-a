#!/usr/bin/env python3
"""Warm restart for tether-booted Orchard systems. No host is needed."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
import device as d
import diagnostics


def load(stage):
    plan=json.loads((stage/'plan.json').read_text())
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=plan['boot_id']:
        raise ValueError('boot changed after preparation')
    if plan.get('loader') == 'file':
        args=['kexec','-s','-l',str(stage/'Image')]
    elif plan.get('loader') == 'legacy':
        args=['kexec','-c','-l',str(stage/'Image'),'--dtb='+str(stage/'merged.dtb')]
    else:
        raise ValueError('missing or invalid loader; prepare the warm entry again')
    args+=['--command-line='+plan['options']]
    if plan['initrd']: args+=['--initrd='+str(stage/'initrd')]
    d.run(*args)
    if Path('/sys/kernel/kexec_loaded').read_text().strip()!='1':
        raise ValueError('kexec did not load an image')
    # The kernel owns copies of the segments now; retain only DT provenance.
    for name in ('Image','initrd','merged.dtb'):
        (stage/name).unlink(missing_ok=True)
    (d.RUN/'developer-loaded').write_text(plan['boot_id']+'\n')
    # Arm the shutdown dispatch here, at load time. The refresh unit no longer runs in
    # the reboot/kexec transaction (a unit needing /boot conflicts with umount.target),
    # so nothing else writes this marker. Without it, dispatch refused and *halted*
    # every warm restart (device journal 2026-11-08: six hops, none jumped).
    (d.RUN/'restart-ready').write_text(plan['boot_id']+'\n')
    return plan


def snapshot():
    """Persist early-initrd snapshot, never derive an old DT from updated /boot."""
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not (d.RUN/'pristine.dtb').is_file() or (d.RUN/'boot-id').read_text().strip()!=boot:
        raise ValueError('matching initrd did not retain pristine DT; cold boot the new bundle first')
    target=Path('/var/lib/orchard-kexec/boots')/boot
    target.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(d.RUN/'pristine.dtb',target/'pristine.dtb')
    return target


def prepare_installed(entry):
    if not Path('/sys/module/apple_wdt/parameters/cold_restart').exists():
        raise ValueError('running kernel lacks the cold reset guard')
    snapshot()
    stage=Path(tempfile.mkdtemp(prefix='orchard-warm.',dir='/var/tmp'))
    shutil.copyfile(Path(__file__).with_name('fdt-merge'),stage/'fdt-merge')
    try:
        plan=d.prepare(stage,False,entry_name=entry)
        load(stage)
        (d.RUN/'developer-loaded').unlink(missing_ok=True)
    except BaseException:
        shutil.rmtree(stage)
        raise
    d.RUN.mkdir(exist_ok=True,parents=True)
    (d.RUN/'loaded.json').write_text(json.dumps(plan,indent=2)+'\n')
    return plan


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='action',required=True)
    for action in ('load','reboot'):
        p=sub.add_parser(action);p.add_argument('entry',nargs='?',default='default')
    for action in ('snapshot','refresh','dispatch','ios','status','update'):
        sub.add_parser(action)
    p=sub.add_parser('stage',help='developer wrapper: staged matching bundle, same engine')
    p.add_argument('directory',type=Path);p.add_argument('operation',choices=('prepare','load','diagnose','bisect'))
    p.add_argument('--profile',choices=d.PROFILES,default='normal')
    p.add_argument('--entry',default='default',help='installed BLS entry for a staged host test')
    p.add_argument('--replace-modules',action='store_true');p.add_argument('--no-aop',action='store_true')
    p.add_argument('--pristine-dtb');p.add_argument('--remote-mac');p.add_argument('--port',type=int,default=6666)
    p.add_argument('--outgoing-no-ans-handoff',action='store_true');p.add_argument('--outgoing-quiesce-gpu',action='store_true')
    p.add_argument('--outgoing-offline-cpu1',action='store_true')
    a=ap.parse_args()
    if os.geteuid()!=0: raise ValueError('run with sudo')
    d.RUN.mkdir(parents=True,exist_ok=True)
    with (d.RUN/'lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if a.action=='stage':
            stage=a.directory.resolve()
            if not __import__('re').fullmatch(r'/var/tmp/orchard-warm\.[A-Za-z0-9]+',str(stage)):
                raise ValueError('invalid stage')
            if a.operation=='prepare': result=d.prepare(stage,a.replace_modules,a.no_aop,a.pristine_dtb,a.profile,entry_name=a.entry)
            elif a.operation=='load': result=load(stage)
            elif a.operation=='diagnose': result=diagnostics.netconsole(a.remote_mac,a.port)
            else: result=diagnostics.bisect(a.outgoing_no_ans_handoff,a.outgoing_quiesce_gpu,a.outgoing_offline_cpu1)
        elif a.action=='snapshot': result=str(snapshot())
        elif a.action=='status':
            print((d.RUN/'loaded.json').read_text() if (d.RUN/'loaded.json').exists() else 'No warm image loaded')
            return
        elif a.action=='ios':
            # Explicit escape hatch only; not used by the Restart action.
            Path('/sys/module/apple_wdt/parameters/cold_restart').write_text('Y\n')
            d.run('kexec','-u');d.run('systemctl','--force','reboot');return
        elif a.action=='refresh':
            (d.RUN/'restart-ready').unlink(missing_ok=True)
            # Before shutdown.target/umount.target: /boot may be a separate fs.
            developer=d.RUN/'developer-loaded'
            armed=(developer.is_file() and developer.read_text().strip() ==
                   Path('/proc/sys/kernel/random/boot_id').read_text().strip() and
                   Path('/sys/kernel/kexec_loaded').read_text().strip() == '1')
            if not armed: prepare_installed('default')
            (d.RUN/'restart-ready').write_text(Path('/proc/sys/kernel/random/boot_id').read_text())
            return
        elif a.action=='dispatch':
            # At this point /boot may already be unmounted. Never load here.
            try:
                if (Path('/sys/kernel/kexec_loaded').read_text().strip() != '1' or
                    (d.RUN/'restart-ready').read_text().strip() !=
                    Path('/proc/sys/kernel/random/boot_id').read_text().strip()):
                    raise ValueError('warm image was not prepared before shutdown')
                d.run('systemctl','--force','kexec')
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                message=f'Warm restart refused: {exc}. No hardware reset. Power off or explicitly request orchard-kexec ios.'
                print(message,file=sys.stderr)
                Path('/dev/kmsg').write_text('<2>'+message+'\n')
                d.run('systemctl','--force','halt')
            return
        else:
            # Always reload here: packages may have replaced even same-path BLS assets.
            try: result=prepare_installed(getattr(a,'entry','default'))
            except (ValueError,OSError,subprocess.SubprocessError):
                # Never leave an old loaded kernel advertised after a failed update.
                subprocess.run(['kexec','-u'],timeout=30,check=False)
                raise
            if getattr(a,'entry','default') != 'default':
                (d.RUN/'developer-loaded').write_text(result['boot_id']+'\n')
            if a.action=='reboot': d.run('systemctl','kexec')
        print(json.dumps(result,indent=2))

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        sys.exit(f'Warm restart refused: {exc}. Linux is still running; no hardware reset was requested.')
