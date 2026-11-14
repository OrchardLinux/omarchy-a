"""Optional outgoing capture and reversible bisects; no import side effects."""
import json
import reset
from pathlib import Path
import re
import subprocess


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout


def netconsole(remote_mac, port=6666):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', remote_mac):
        raise ValueError('invalid Mac ethernet address')
    if not 1024 <= port <= 65535:
        raise ValueError('invalid UDP port')
    route = json.loads(run('ip', '-j', 'route', 'get', '172.16.42.2'))
    if len(route) != 1 or route[0].get('dev') != 'usb0' or route[0].get('prefsrc') != '172.16.42.1':
        raise ValueError('netconsole requires usb0 172.16.42.1 -> 172.16.42.2')
    run('modprobe', 'netconsole')
    if not Path('/sys/kernel/config/netconsole').exists():
        run('mount', '-t', 'configfs', 'none', '/sys/kernel/config')
    target = Path('/sys/kernel/config/netconsole/orchard-warm')
    target.mkdir(exist_ok=True)
    # A new target starts disabled, and writing 0 to it fails with EINVAL.
    if (target/'enabled').read_text().strip() not in ('0', ''):
        (target/'enabled').write_text('0\n')
    for key, value in dict(dev_name='usb0', local_ip='172.16.42.1', local_port='6665',
                           remote_ip='172.16.42.2', remote_port=str(port), remote_mac=remote_mac).items():
        (target/key).write_text(value+'\n')
    (target/'enabled').write_text('1\n')
    # Only for this diagnostic run: INFO/DEBUG shutdown records reach netconsole
    # and ramoops. fbcon=map:9 keeps them off the panel; this is not a GPU fix.
    values = {}
    for path, value in [('/proc/sys/kernel/printk', '8'),
                        ('/sys/module/kernel/parameters/initcall_debug', 'Y'),
                        ('/sys/module/printk/parameters/ignore_loglevel', 'Y')]:
        p=Path(path)
        if p.exists():
            values[path]=p.read_text().strip()
            if path.endswith('/printk'):
                value=' '.join([value]+values[path].split()[1:])
            p.write_text(value+'\n')
    marker='orchard-warm netconsole ready boot='+Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    Path('/dev/kmsg').write_text('<6>'+marker+'\n')
    return dict(marker=marker, target=str(target), usb_mac=Path('/sys/class/net/usb0/address').read_text().strip(),
                remote_mac=remote_mac, previous=values)


def bisect(no_ans=False, quiesce_gpu=False, offline_cpu1=False):
    result={"reset_guard": reset.status()}
    if no_ans:
        p=Path('/sys/module/pcie_apple_h9p/parameters/ans_keep_power')
        result['ans_keep_power_before']=p.read_text().strip()
        # This changes outgoing policy only. A paired cold baseline is still
        # required to compare the full boot history. Do not unbind live NVMe.
        p.write_text('N\n');result['ans_keep_power_after']=p.read_text().strip()
    if quiesce_gpu:
        # Lab's production td-kexec path; leave clients stopped and driver bound.
        # Unbinding G5P/AOP would enter remove paths and is not a warm equivalent.
        run('systemctl','stop','greetd.service')
        p=Path('/sys/bus/platform/devices/201000000.gpu/command')
        p.write_text('td-kexec\n');result['gpu']='td-kexec (one-shot; no more GPU work this boot)'
    if offline_cpu1:
        p=Path('/sys/devices/system/cpu/cpu1/online')
        if p.exists():
            p.write_text('0\n');result['cpu1_online']=p.read_text().strip()
    return result
