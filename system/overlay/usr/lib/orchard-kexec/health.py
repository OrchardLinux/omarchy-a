#!/usr/bin/env python3
"""Post-boot health gate: refuse to call a boot usable while NVMe I/O crawls.

Usage: kexec-health-gate.py [--expect-boot-id UUID] [--min-uptime 120]
                            [--min-observe 60] [--interval 10] ...
OMARCHY_SSH overrides the SSH wrapper (scripts/omarchy/ssh.sh).

Each probe runs one bounded SSH command that times `sudo -n true`, reads
16 KiB from /dev/nvme0n1 with O_DIRECT (a real NVMe command, not the page
cache), and compares the nvme0q IRQ count before and after. It also checks
the boot's own dmesg for NVMe timeout lines. The gate passes only after
uptime >= --min-uptime and --min-observe seconds of clean probes. Exit 0 =
healthy, 1 = unhealthy (last line "HEALTH FAIL: ..."), 2 = usage.
Background: docs/boot/ds-kexec-nvme-crawl.md.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
MARK = 'linux-a9-health-probe'
# One SSH round trip. Every step that can block on the disk has a device-side
# timeout; the Mac-side subprocess timeout covers a hung SSH or D-state hang.
PROBE = r'''
export LC_ALL=C
ms() { echo $(( $(date +%s%N) / 1000000 )); }
echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
echo "uptime=$(cut -d' ' -f1 /proc/uptime)"
echo "load=$(cut -d' ' -f1 /proc/loadavg)"
echo "irq_before=$(grep -m1 'nvme0q' /proc/interrupts)"
t=$(ms); timeout 8 sudo -n true; rc=$?; echo "sudo_rc=$rc"; echo "sudo_ms=$(( $(ms) - t ))"
skip=$(( (RANDOM * 32768 + RANDOM) % 262144 ))
t=$(ms)
timeout 8 sudo -n dd if=/dev/nvme0n1 of=/dev/null bs=4096 count=4 skip=$skip iflag=direct status=none
rc=$?; echo "read_rc=$rc"; echo "read_ms=$(( $(ms) - t ))"
echo "irq_after=$(grep -m1 'nvme0q' /proc/interrupts)"
log=$(timeout 8 sudo -n dmesg); echo "dmesg_rc=$?"
printf '%s\n' "$log" | grep -v -E 'omarchy-rd|AOP-PREV' |
	grep -E 'completion polled|Apple ANS: timeout|I/O tag .* timeout|drained every CQ|IRQ rescue|MSI resumed|nvme.*(reset controller|disable controller|Disabling device)' |
	tail -n 40 | sed 's/^/dmesg: /'
echo "done=1"
'''
# NVMe trouble in this boot's kernel log. Lines replayed from earlier boots
# (pstore/ramoops, "[omarchy-rd]: ...") are not this boot and are ignored.
# Rescue drains also log "drained every CQ"; "IRQ rescue every N ms" is the
# opt-in rescue's bring-up line and is not a failure.
BAD = re.compile(r'completion polled|Apple ANS: timeout|I/O tag .* timeout|'
                 r'drained every CQ|reset controller|disable controller|'
                 r'Disabling device')
REPLAY = re.compile(r'omarchy-rd|AOP-PREV')


def irq_total(line):
    """Sum the per-CPU counts of a /proc/interrupts line; None if absent."""
    fields = line.split()
    if not fields or not fields[0].endswith(':'):
        return None
    total = 0
    seen = False
    for f in fields[1:]:
        if not f.isdigit():
            break
        total += int(f)
        seen = True
    return total if seen else None


def parse(text):
    probe = {'dmesg': []}
    for line in text.splitlines():
        if line.startswith('dmesg: '):
            probe['dmesg'].append(line[7:])
        elif '=' in line:
            key, value = line.split('=', 1)
            probe[key.strip()] = value.strip()
    return probe


def judge(probe, args, boot_id=None):
    """Return a failure reason, or None if this probe is healthy."""
    if probe.get('done') != '1':
        return 'probe output incomplete'
    if boot_id and probe.get('boot_id') != boot_id:
        return f'boot_id changed: {boot_id} -> {probe.get("boot_id")}'
    if probe.get('dmesg_rc') != '0':
        return f'sudo -n dmesg failed rc={probe.get("dmesg_rc")}'
    native = [l for l in probe['dmesg'] if BAD.search(l) and not REPLAY.search(l)]
    if native:
        return f'{len(native)} NVMe timeout/recovery line(s) in this boot, first: {native[0][:200]}'
    try:
        sudo_rc, sudo_ms = int(probe['sudo_rc']), int(probe['sudo_ms'])
        read_rc, read_ms = int(probe['read_rc']), int(probe['read_ms'])
    except (KeyError, ValueError):
        return 'probe output unparseable'
    if sudo_rc:
        return f'sudo -n true failed rc={sudo_rc} after {sudo_ms} ms'
    if sudo_ms > args.sudo_max * 1000:
        return f'sudo -n true took {sudo_ms} ms (> {args.sudo_max} s)'
    if read_rc:
        return f'direct NVMe read failed rc={read_rc} after {read_ms} ms'
    if read_ms > args.read_max * 1000:
        return f'direct NVMe read took {read_ms} ms (> {args.read_max} s)'
    before = irq_total(probe.get('irq_before', ''))
    after = irq_total(probe.get('irq_after', ''))
    if before is None or after is None:
        return 'no nvme0q line in /proc/interrupts'
    if after <= before:
        return (f'nvme0q IRQ count stayed at {after} across a direct read: '
                'the completion was polled, not signalled (lost MSI)')
    return None


def probe_once(args):
    try:
        r = subprocess.run(['bash', '-s', '--', MARK], input=PROBE, text=True,
                           capture_output=True, timeout=args.ssh_timeout)
    except subprocess.TimeoutExpired:
        return None, f'local probe hung > {args.ssh_timeout} s'
    if r.returncode != 0 and 'done=1' not in r.stdout:
        return None, f'local probe failed rc={r.returncode}: {r.stderr.strip()[:200]}'
    return parse(r.stdout), None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--expect-boot-id', help='fail if the device is not on this boot')
    ap.add_argument('--min-uptime', type=float, default=120,
                    help='keep probing until the boot is this old (s)')
    ap.add_argument('--min-observe', type=float, default=60,
                    help='and for at least this long (s)')
    ap.add_argument('--interval', type=float, default=10, help='between probes (s)')
    ap.add_argument('--sudo-max', type=float, default=5, help='max sudo -n true (s)')
    ap.add_argument('--read-max', type=float, default=3, help='max direct read (s)')
    ap.add_argument('--ssh-timeout', type=float, default=30, help='per probe (s)')
    ap.add_argument('--max-probes', type=int, default=60, help='hard bound')
    ap.add_argument('--quick', action='store_true',
                    help='two probes 2 s apart, no uptime floor (before each test step)')
    args = ap.parse_args(argv)
    if args.quick:
        args.min_uptime, args.min_observe, args.interval = 0, 0, 2
    if min(args.min_uptime, args.min_observe, args.interval) < 0 or args.max_probes < 1:
        ap.error('negative timing or no probes')

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import reset
    print('Reset guard: ' + reset.status(), file=sys.stderr)
    start = time.monotonic()
    boot_id = args.expect_boot_id
    passed = 0
    retried = False
    for n in range(1, args.max_probes + 1):
        probe, err = probe_once(args)
        if err is None:
            err = judge(probe, args, boot_id)
            boot_id = boot_id or probe.get('boot_id')
        elapsed = time.monotonic() - start
        if err and err.startswith('SSH probe') and not retried:
            # One immediate retry: a USB-link blip is not a crawl; two are.
            retried = True
            print(f'health: probe {n} +{elapsed:.0f}s {err}; retrying once', file=sys.stderr)
            continue
        if err:
            print(f'HEALTH FAIL: {err} (probe {n}, +{elapsed:.0f}s, '
                  f'{passed} clean probes before)', file=sys.stderr)
            return 1
        retried = False
        passed += 1
        uptime = float(probe.get('uptime', '0') or 0)
        print(f'health: probe {n} +{elapsed:.0f}s uptime {uptime:.0f}s load {probe.get("load")} '
              f'sudo {probe["sudo_ms"]}ms read {probe["read_ms"]}ms nvme irq '
              f'{irq_total(probe["irq_before"])}->{irq_total(probe["irq_after"])} ok',
              file=sys.stderr)
        if uptime >= args.min_uptime and elapsed >= args.min_observe and passed >= 2:
            print(f'HEALTH PASS: {passed} clean probes over {elapsed:.0f}s, uptime {uptime:.0f}s, '
                  f'boot_id {boot_id}')
            return 0
        time.sleep(args.interval)
    print(f'HEALTH FAIL: no verdict after {args.max_probes} probes', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
