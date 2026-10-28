#!/usr/bin/env python3
"""Record the P105 root, package snapshot and source-built desktop inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','result','snapshot','components','desktop'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--release',required=True)
    args=parser.parse_args()
    binaries=['usr/lib/systemd/systemd','usr/bin/qs','usr/bin/labwc','usr/bin/omacalc',
              'usr/libexec/omarchy-wtype','home/tablet/.local/share/omarchy-ipad/trials/wvkbd-mobintl-v0.20-font18-special15-state']
    for name in binaries:
        header=(args.root/name).read_bytes()[:52]
        if (len(header)!=52 or header[:7]!=b'\x7fELF\x01\x01\x01' or header[18:20]!=b'\x28\x00' or
                not struct.unpack_from('<I',header,36)[0]&0x400):
            raise ValueError('Expected an ARM32 hard-float runtime executable: '+name)
    archive=args.result/'rootfs.tar.gz'
    record={'schema':1,'kind':'omarchy-a.p105.base','profile':'p105','architecture':'armv7h','release':args.release,
            'bytes':archive.stat().st_size,'sha256':sha(archive),'compression':'gzip',
            'packages_lock_sha256':sha(args.result/'packages.lock'),
            'snapshot':{p.name:sha(p) for p in sorted(args.snapshot.iterdir()) if p.is_file()},
            'desktop':json.loads((args.desktop/'p105-desktop.json').read_text()),
            'components':{name:json.loads((args.components/name/'manifest.json').read_text())
                          for name in ('keyboard','support','apps','signed-apps')},
            'hardware':json.loads((args.root/'etc/cascadia/p105-hardware-input.json').read_text()),
            'binaries':{name:sha(args.root/name) for name in binaries}}
    (args.result/'rootfs.tar.gz.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':
    main()
