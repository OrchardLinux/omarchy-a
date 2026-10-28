"""Assemble a public P105 NFS root release from the native userspace producer."""
import argparse
import json
from pathlib import Path
import shutil

from .audit import audit, inventory, sha


def build(base,output):
    base,output=Path(base),Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Choose a fresh P105 release directory')
    archive=base/'rootfs.tar.gz'
    receipt=json.loads((base/'rootfs.tar.gz.json').read_text())
    if (receipt.get('kind'),receipt.get('profile'),receipt.get('architecture'))!=('omarchy-a.p105.base','p105','armv7h'):
        raise ValueError('Expected a native P105 base receipt')
    if archive.stat().st_size!=receipt['bytes'] or sha(archive)!=receipt['sha256']:
        raise ValueError('P105 base stream differs from its receipt')
    if sha(base/'packages.lock')!=receipt['packages_lock_sha256']:
        raise ValueError('P105 package inventory differs from its receipt')
    catalog,_=inventory(archive)
    output.mkdir(parents=True)
    for source,target in [('rootfs.tar.gz','rootfs.tar.gz'),('packages.lock','packages.lock'),
                          ('rootfs.tar.gz.json','build-receipt.json'),('desktop-sources.tar.gz','desktop-sources.tar.gz')]:
        shutil.copy2(base/source,output/target)
    (output/'rootfs.catalog.json').write_text(json.dumps(catalog,sort_keys=True,separators=(',',':'))+'\n')
    record={'schema':1,'kind':'omarchy-a.nfs-root','distro':'omarchy-a','profile':'p105','architecture':'armv7h',
            'release':receipt['release'],'min_orchard':'0.1.11','protocol':1,'boot_method':'jailbreak-kdfu',
            'qualification':'pending-physical-boot','root':{'file':'rootfs.tar.gz','bytes':archive.stat().st_size,
                'sha256':receipt['sha256'],'compression':'gzip','members':len(catalog),
                'expanded_bytes':sum(v.get('bytes',0) for v in catalog.values())},
            'catalog_sha256':sha(output/'rootfs.catalog.json'),
            'packages_lock_sha256':receipt['packages_lock_sha256'],
            'sources_sha256':sha(output/'desktop-sources.tar.gz'),
            'compatibility':{'board':'apple,p105ap','runtime':'p105-systemd-v1','kernel':'6.12.0',
                'kernel_commit':'adc218676eef25575469234709c2d87185ca223a','flash_controller':'disabled',
                'hardware_package':receipt['hardware']['package'],'hardware_overlay':receipt['hardware']['files']},
            'desktop':{'renderer':'pixman','qtquick':'software','panel':[768,1024],'scale':1},
            'root_service':'host NFSv3/TCP over USB for the entire session'}
    (output/'rootfs.json').write_text(json.dumps(record,indent=2)+'\n')
    audit(output)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True,help='result directory from system/build-rootfs p105')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build(args.base,args.output)


if __name__=='__main__':
    main()
