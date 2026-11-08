#!/usr/bin/env python3
"""Device half of warm-reboot.sh. Uploaded and called explicitly; no import side effects."""
import argparse
from functools import cmp_to_key
import fnmatch
import gzip
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

BOOT = Path('/boot')
RUN = Path('/run/orchard-kexec')

def run(*args, **kw):
    return subprocess.run(args, check=True, timeout=kw.pop('timeout', 60), **kw)

def fields(path):
    values = {}
    for line in path.read_text().splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and not parts[0].startswith('#'):
            values.setdefault(parts[0].lower(), []).append(parts[1].strip())
    return values

def value(entry, key, default=''):
    return entry.get(key, [default])[-1]

def version_cmp(a, b):
    # Same ordering as Orchard m1n1 bls.rs (strverscmp_improved).
    def cmp(x, y): return (x > y) - (x < y)
    if not a or not b:
        return cmp(a, b)
    while True:
        a = re.sub(r'^[^a-zA-Z0-9~^.-]+', '', a)
        b = re.sub(r'^[^a-zA-Z0-9~^.-]+', '', b)
        for separator in '~':
            x, y = a.startswith(separator), b.startswith(separator)
            if x != y: return -1 if x else 1
            if x: a, b = a[1:], b[1:]
        if not a or not b: return cmp(a, b)
        for separator in '-^.':
            x, y = a.startswith(separator), b.startswith(separator)
            if x != y: return -1 if x else 1
            if x: a, b = a[1:], b[1:]
        numeric = a[:1].isdigit() or b[:1].isdigit()
        pattern = r'^\d*' if numeric else r'^[a-zA-Z]*'
        x, y = re.match(pattern, a)[0], re.match(pattern, b)[0]
        if numeric:
            sx, sy = x.lstrip('0'), y.lstrip('0')
            r = cmp(bool(x), bool(y)) or cmp(len(sx), len(sy)) or cmp(sx, sy)
        else:
            r = cmp(x, y)
        if r: return r
        a, b = a[len(x):], b[len(y):]

def entry_cmp(a, b):
    pa, ea = a; pb, eb = b
    ka, kb = value(ea, 'sort-key'), value(eb, 'sort-key')
    if bool(ka) != bool(kb): return -1 if ka else 1
    if ka:
        for x, y in ((ka, kb), (value(ea, 'machine-id'), value(eb, 'machine-id'))):
            if x != y: return (x > y) - (x < y)
        r = version_cmp(value(eb, 'version'), value(ea, 'version'))
        if r: return r
    return version_cmp(pb.stem, pa.stem)

def boot_path(name):
    if not name or '..' in Path(name).parts:
        raise ValueError(f'invalid BLS path: {name!r}')
    p = (BOOT / name.lstrip('/')).resolve()
    if not p.is_relative_to(BOOT.resolve()) or not p.is_file():
        raise ValueError(f'missing or escaping BLS path: {name}')
    return p

def release_of(path):
    data = path.read_bytes()
    if data.startswith(b'\x1f\x8b'): data = gzip.decompress(data)
    if data[56:60] != b'ARM\x64': raise ValueError(f'not an arm64 Image: {path}')
    m = re.search(rb'Linux version ([^\s]+) ', data)
    if not m: raise ValueError(f'no kernel release in {path}')
    return m[1].decode()

def select_entry(entries, name='default'):
    if name != 'default':
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', name):
            raise ValueError('invalid BLS entry name')
        found = [(p, e) for p, e in entries if p.name == name or p.stem == name]
        if len(found) != 1: raise ValueError('missing or ambiguous BLS entry')
        return found[0]
    loader = BOOT / 'loader/loader.conf'
    pattern = value(fields(loader), 'default') if loader.exists() else ''
    if pattern.startswith('@'): raise ValueError(f'unsupported loader default {pattern}')
    candidates = [(p, e) for p, e in entries if not pattern or
                  fnmatch.fnmatchcase(p.name, pattern) or fnmatch.fnmatchcase(p.stem, pattern)]
    if not candidates: raise ValueError('no matching default BLS entry')
    return sorted(candidates, key=cmp_to_key(entry_cmp))[0]

PROFILES = ('normal', 'safe', 'smp', 'display', 'gpu-bind', 'gpu', 'full')

def warm_options(options, stage, no_aop=False, profile='normal'):
    # Keep root and ordinary BLS options; replace warm provenance and AOP policy.
    options = re.sub(r'(?:^|\s)orchard_warm.dtb=\S+', '', options).strip()
    if profile not in PROFILES:
        raise ValueError('unknown warm profile')
    # Retain info-level checkpoints in ramoops; fbcon=map:9 keeps the console
    # off this panel. Lower loglevel would also discard the pstore breadcrumbs.
    forced = {'panic': '0', 'apple_wdt.cold_restart': '0', 'loglevel': '7',
              'fbcon': 'map:9', 'vt.global_cursor_default': '0'}
    if profile != 'normal':
        forced.update(nr_cpus='1' if profile == 'safe' else '2',
                      **{'a9_gpu_drm.enable': '1' if profile in ('gpu-bind', 'gpu', 'full') else '0',
                         'a9_gpu_drm.autoboot': '1' if profile in ('gpu', 'full') else '0',
                         'systemd.unit': 'multi-user.target'})
    options = ' '.join(t for t in options.split() if t.split('=', 1)[0] not in forced
                       and t not in ('quiet', 'ignore_loglevel', 'debug'))
    options += ' ' + ' '.join(f'{k}={v}' for k, v in forced.items())
    if no_aop or profile in ('safe', 'smp', 'display', 'gpu-bind', 'gpu'):
        blocked = []
        for m in re.finditer(r'(?:^|\s)module_blacklist=(\S+)', options):
            blocked.extend(m[1].split(','))
        blocked.append('apple_aop')
        options = re.sub(r'(?:^|\s)module_blacklist=\S+', '', options).strip()
        options += ' module_blacklist=' + ','.join(dict.fromkeys(blocked))
    options = ' '.join(t for t in options.split() if not t.startswith('crash_kexec_post_notifiers'))
    options += f' crash_kexec_post_notifiers orchard_warm.dtb={stage}/pristine.dtb'
    return options

def profile_dtb(source, dest, profile, merger):
    """Save the *effective pristine* DT, so diagnostic status is not inherited.

    Editing only the merged tree would look like a loader fixup on the next hop
    and silently keep ADBE disabled even when the next profile enables it.
    """
    loader = importlib.machinery.SourceFileLoader('orchard_fdt', str(merger))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    fdt = importlib.util.module_from_spec(spec)
    loader.exec_module(fdt)
    root, reservations, cpu = fdt.parse(source.read_bytes())
    disabled = []
    if profile in ('safe', 'smp'):
        for path, node in fdt.index(root).items():
            if b'apple,s8000-display-pipe' in node.props.get('compatible', b'').split(b'\0'):
                node.props['status'] = b'disabled\0'
                disabled.append(path)
        if len(disabled) != 1:
            raise ValueError('warm profile requires exactly one J71t ADBE node')
    dest.write_bytes(fdt.serialize(root, reservations, cpu))
    return disabled

def guard_outgoing(profile):
    guard = Path('/sys/module/apple_wdt/parameters/cold_restart')
    if not guard.exists():
        if profile != 'normal':
            raise ValueError('cold boot the new kernel first: outgoing cold_restart guard is missing')
        return 'unavailable on outgoing kernel; target guard requested'
    # A running firmware/userspace watchdog is separate from the reset fallback.
    for state in Path('/sys/class/watchdog').glob('watchdog*/state'):
        if state.read_text().strip() != 'inactive':
            raise ValueError('active watchdog; stop its owner before a warm test')
    guard.write_text('N\n')
    if guard.read_text().strip() != 'N':
        raise ValueError('could not disable outgoing cold restart')
    Path('/proc/sys/kernel/panic').write_text('0\n')
    return 'outgoing cold_restart=N'

def check_psci(possible, tree=Path('/proc/device-tree')):
    if possible == '0':
        return  # nr_cpus=1 diagnostic cold boot; maxcpus=1 is insufficient.
    method = tree / 'psci/method'
    cpus = [cpu for cpu in (tree / 'cpus').glob('cpu@*')
            if not (cpu / 'status').exists() or
            (cpu / 'status').read_bytes().rstrip(b'\0') in (b'okay', b'ok')]
    if (not method.exists() or method.read_bytes().rstrip(b'\0') != b'smc' or
            not cpus or any(not (cpu / 'enable-method').exists() or
                            (cpu / 'enable-method').read_bytes().rstrip(b'\0') != b'psci'
                            for cpu in cpus)):
        raise ValueError('SMP kexec needs PSCI m1n1 (method=smc, CPU enable-method=psci). '
                         'Cold boot with that loader or nr_cpus=1 first.')


def prepare(stage, replace, no_aop=False, pristine_dtb=None, profile='normal', entry_name='default'):
    for tool in ('kexec', 'depmod'):
        if not shutil.which(tool): raise ValueError(f'missing {tool}; sudo pacman -S kexec-tools kmod (needs network)')
    possible = Path('/sys/devices/system/cpu/possible').read_text().strip()
    check_psci(possible)
    entries = [(p, fields(p)) for p in sorted((BOOT / 'loader/entries').glob('*.conf'))]
    path, entry = select_entry(entries, entry_name)
    if any(k in entry for k in ('efi', 'uki', 'devicetree-overlay')) or value(entry, 'architecture', 'aa64') != 'aa64':
        raise ValueError(f'unsupported BLS entry: {path}')
    options = value(entry, 'options')
    extra = stage / 'extra-options'
    if extra.exists():
        text = extra.read_text()
        if any(ord(c) < 32 for c in text): raise ValueError('invalid extra options')
        options = (options + ' ' + text).strip()
    if not re.search(r'(^|\s)root=PARTUUID=\S+', options): raise ValueError('BLS options lack root=PARTUUID')
    target_kernel = boot_path(value(entry, 'linux'))
    target_dtb = boot_path(value(entry, 'devicetree'))
    current_release = run('uname', '-r', capture_output=True, text=True).stdout.strip()
    cmdline = Path('/proc/cmdline').read_text().strip()
    custom = (stage / 'kernel.release').exists()
    if custom:
        release = (stage / 'kernel.release').read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9._+-]+', release): raise ValueError('invalid kernel.release')
        if release == current_release and not replace:
            raise ValueError(f'refusing to overwrite running modules {release}; use --replace-modules explicitly')
        target_kernel, target_dtb = stage / 'Image.gz', stage / 'dtb'
        if release_of(target_kernel) != release: raise ValueError('kernel.release disagrees with Image')
    else:
        release = release_of(target_kernel)
    # Resolve the exact pristine DT of the running cold/warm entry; never pass a raw build DT to kexec.
    marker = re.search(r'(?:^|\s)orchard_warm.dtb=(\S+)', cmdline)
    if (RUN/'pristine.dtb').is_file():
        if (RUN/'boot-id').read_text().strip() != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
            raise ValueError('stale running pristine DT snapshot')
        old = RUN/'pristine.dtb'
    elif marker:
        old = Path(marker[1])
        if not re.fullmatch(r'/var/tmp/orchard-warm\.[A-Za-z0-9]+/pristine.dtb', str(old)):
            raise ValueError('invalid running DT provenance marker')
    else:
        root = re.search(r'(?:^|\s)root=(\S+)', cmdline)
        matches = []
        for _, e in entries:
            if not root or f'root={root[1]}' not in value(e, 'options').split(): continue
            if release_of(boot_path(value(e, 'linux'))) == current_release:
                matches.append(boot_path(value(e, 'devicetree')))
        if matches and len({p.read_bytes() for p in matches}) == 1:
            old = matches[0]
        elif pristine_dtb:
            # Explicit operator choice for the ambiguous case (entries sharing one kernel.release).
            old = Path(pristine_dtb)
            if not re.fullmatch(r'(/boot|/var/tmp/oi-backup-[A-Za-z0-9-]+)/[A-Za-z0-9._/+-]+', str(old)) \
                    or not old.is_file() or old.read_bytes()[:4] != b'\xd0\x0d\xfe\xed':
                raise ValueError('--pristine-dtb is not a device tree under /boot or /var/tmp/oi-backup-*')
        else:
            raise ValueError('running pristine DT is ambiguous or absent; keep its exact cold-boot BLS entry '
                             'installed, or pass --pristine-dtb')
    disabled = profile_dtb(target_dtb, stage / 'pristine.dtb', profile, stage / 'fdt-merge')
    # Canonicalize both pristine trees: reserialization alone is not a DT change.
    merger = importlib.machinery.SourceFileLoader('orchard_compare_fdt', str(stage / 'fdt-merge')).load_module()
    def canonical(path):
        tree, reservations, cpu = merger.parse(path.read_bytes())
        return ({name: node.props for name, node in merger.index(tree).items()},
                sorted(reservations), cpu)
    loader = 'file' if canonical(old) == canonical(stage / 'pristine.dtb') else 'legacy'
    if loader == 'legacy':
        run('python3', str(stage / 'fdt-merge'), '--old', str(old), '--running', '/sys/firmware/fdt',
            '--new', str(stage / 'pristine.dtb'), '-o', str(stage / 'merged.dtb'))
    # file_load copies the kernel's live FDT and adds linux,booted-from-kexec
    # in drivers/of/kexec.c. Never fall back silently after a failed file load.
    data = target_kernel.read_bytes()
    (stage / 'Image').write_bytes(gzip.decompress(data) if data.startswith(b'\x1f\x8b') else data)
    initrds = [boot_path(p) for p in entry.get('initrd', [])]
    if custom and not (stage / 'initrd').is_file():
        raise ValueError('custom bundle requires its matching initrd; refusing BLS fallback')
    if not initrds and not custom:
        raise ValueError('installed BLS entry requires an initrd')
    if initrds and not custom:
        with (stage / 'initrd').open('wb') as out:
            for p in initrds:
                with p.open('rb') as src: shutil.copyfileobj(src, out)
    if custom:
        source = stage / 'lib/modules' / release
        if not source.is_dir(): raise ValueError('missing uploaded modules')
        # Preserve the installed BLS kernel/initrd/dtb assets within this directory.
        shutil.copytree(source, Path('/usr/lib/modules') / release, dirs_exist_ok=True)
        run('depmod', '-a', release)
    options = warm_options(options, stage, no_aop, profile)
    guard = guard_outgoing(profile)
    plan = dict(entry=path.name, release=release, boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                options=options, initrd=(stage / 'initrd').is_file(), stage=str(stage),
                profile=profile, loader=loader, disabled_nodes=disabled, reset_guard=guard,
                notes=['AOP explicitly disabled.' if no_aop else 'AOP reload requires a certified outgoing quiesce; untested states refuse.',
                       'G5P uses mode 3 on kexec; warm peripheral parity still needs Orchard device validation.'])
    (stage / 'plan.json').write_text(json.dumps(plan))
    return plan
