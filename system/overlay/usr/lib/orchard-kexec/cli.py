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
import reset


def warm_supported():
    """Whether this system has what a warm restart uses: the running kernel's
    kexec support, kexec-tools and the kernel's tethered reset guard. Without
    them Restart is an ordinary reboot. The guard is the board's own: only a
    kernel whose watchdog describes the tethered boot provides it."""
    try:
        if not Path('/sys/kernel/kexec_loaded').exists() or shutil.which('kexec') is None:
            return False
        reset.backend()
    except (OSError, ValueError):
        return False
    return True


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


def unload():
    """Invalidate provenance before touching the kernel's armed image."""
    for name in ('restart-ready', 'developer-loaded', 'loaded.json'):
        (d.RUN/name).unlink(missing_ok=True)
    d.run('kexec', '-u')


def cold_reset(reason=None):
    """Best-effort cold escape; one failed step must not suppress reboot."""
    def note(message):
        try:
            print(message, file=sys.stderr)
        except OSError:
            pass
        try:
            Path('/dev/kmsg').write_text('<0>' + message + '\n')
        except OSError:
            pass
    if reason:
        note(f'Warm restart aborted: {reason}; unloading kexec and cold-resetting to iOS.')
    try:
        reset.select(warm=False)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        note(f'Cold escape: guard selection failed: {exc}; using reboot mode ABI')
        try:
            mode = Path('/sys/kernel/reboot/mode')
            mode.write_text('cold\n')
            if mode.read_text().strip() != 'cold':
                raise ValueError('cold mode did not read back')
        except (ValueError, OSError) as mode_error:
            note(f'Cold escape: cold mode unavailable: {mode_error}; arming native watchdog')
            try:
                if Path('/sys/class/watchdog/watchdog0/identity').read_text().strip() != 'Apple SoC Watchdog':
                    raise ValueError('native Apple watchdog unavailable')
                fd = os.open('/dev/watchdog0', os.O_WRONLY | os.O_CLOEXEC)
                try:
                    import struct
                    fcntl.ioctl(fd, 0xc0045706, struct.pack('I', 1))  # WDIOC_SETTIMEOUT
                    os.write(fd, b'\0')  # Keep armed: never write the magic-close byte.
                finally:
                    os.close(fd)
                note('Cold escape: native watchdog armed; no warm reboot requested')
                return True
            except (ValueError, OSError) as watchdog_error:
                note(f'Cold escape: native watchdog failed: {watchdog_error}; refusing warm reset')
                return False
    try:
        unload()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        note(f'Cold escape: unload kexec failed: {exc}')
    try:
        d.run('systemctl', '--force', 'reboot')
        return True
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        note(f'Cold escape: reboot request failed: {exc}; trying emergency restart')
    try:
        # Also try the standard ABI if guard discovery or read-back failed.
        Path('/sys/kernel/reboot/mode').write_text('cold\n')
    except OSError as exc:
        note(f'Cold escape: emergency cold selection failed: {exc}')
    try:
        Path('/proc/sysrq-trigger').write_text('b')
    except OSError as exc:
        note(f'Cold escape: emergency restart failed: {exc}')
    # A returning emergency restart is failure: never trigger SuccessAction=kexec.
    return False


def select_default(entry):
    """Change selection synchronously; never leave the previous image armed."""
    entries = [(p, d.fields(p)) for p in sorted((d.BOOT/'loader/entries').glob('*.conf'))]
    path, _ = d.select_entry(entries, entry)
    loader = d.BOOT/'loader/loader.conf'
    lines = loader.read_text().splitlines() if loader.exists() else []
    lines = [line for line in lines if not line.split() or line.split()[0] != 'default']
    unload()
    # Write only after unload succeeds. On prepare failure the new default remains
    # selected, with no stale image; refresh can retry while /boot is available.
    temporary = loader.with_name('loader.conf.orchard-new')
    temporary.write_text('\n'.join(lines + ['default ' + path.name]) + '\n')
    temporary.replace(loader)
    try:
        return prepare_installed('default')
    except BaseException:
        unload()
        raise


def prepare_reboot():
    """Shutdown-only: no /boot, systemctl call, dispatch, or halt."""
    if Path('/sys/kernel/kexec_loaded').read_text().strip() == '1':
        reset.select(warm=False)
    else:
        try:
            reset.backend()
        except ValueError:
            return
        reset.select(warm=False)


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
    reset.backend()
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
    for action in ('load','reboot','select'):
        p=sub.add_parser(action);p.add_argument('entry',nargs='?',default='default')
    for action in ('snapshot','refresh','dispatch','ios','cold','status','update','prepare-reboot','supported'):
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
    if a.action == 'supported':
        raise SystemExit(0 if warm_supported() else 1)
    if a.action == 'prepare-reboot':
        prepare_reboot()
        return
    if a.action in ('load', 'refresh', 'reboot', 'update', 'dispatch', 'select'):
        qualified = warm_supported()
        if not qualified:
            if a.action == 'dispatch':
                if cold_reset('this system has no kexec support or reset guard for a warm restart') is False:
                    raise SystemExit(1)
            elif a.action == 'reboot':
                d.run('systemctl', 'reboot')
            return
    if os.geteuid()!=0: raise ValueError('run with sudo')
    d.RUN.mkdir(parents=True,exist_ok=True)
    if a.action == 'dispatch' and (d.RUN/'gpu-quiesce-failed').exists():
        if cold_reset('GPU td-kexec failed or timed out') is False:
            raise SystemExit(1)
        return
    with (d.RUN/'lock').open('w') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            if a.action != 'dispatch':
                raise
            if cold_reset('shutdown dispatch lock unavailable') is False:
                raise SystemExit(1)
            return
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
            print('Reset guard: ' + reset.status())
            print((d.RUN/'loaded.json').read_text() if (d.RUN/'loaded.json').exists() else 'No warm image loaded')
            return
        elif a.action=='cold':
            # Preserve normal reboot on systems without a tethered guard.
            try: reset.backend()
            except ValueError: return
            reset.select(warm=False)
            return
        elif a.action=='ios':
            # Explicit escape hatch only; not used by the Restart action.
            if cold_reset() is False:
                raise SystemExit(1)
            return
        elif a.action=='select':
            result=select_default(a.entry)
        elif a.action=='refresh':
            # Selection and package changes always mean the current default.
            # Invalidate the old image first; failed preparation cannot leave it armed.
            unload()
            try:
                prepare_installed('default')
            except BaseException:
                unload()
                raise
            return
        elif a.action=='dispatch':
            if (d.RUN/'gpu-quiesce-failed').exists():
                if cold_reset('GPU td-kexec failed or timed out') is False:
                    raise SystemExit(1)
                return
            # At this point /boot may already be unmounted. Never load here.
            try:
                if (Path('/sys/kernel/kexec_loaded').read_text().strip() != '1' or
                    (d.RUN/'restart-ready').read_text().strip() !=
                    Path('/proc/sys/kernel/random/boot_id').read_text().strip()):
                    raise ValueError('warm image was not prepared before shutdown')
                d.guard_outgoing('normal', arm=True)
                d.run('systemctl','--force','kexec')
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                if cold_reset(f'warm dispatch refused: {exc}') is False:
                    raise SystemExit(1)
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
