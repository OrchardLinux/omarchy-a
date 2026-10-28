"""Exercise a finished P105 artifact in a disposable ARMv7 desktop session."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess

from .audit import audit

PROJECT=Path(__file__).resolve().parents[2]


def smoke(release,builder_image,output):
    release,output=Path(release),Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Choose a fresh P105 desktop validation directory')
    if not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}',builder_image):
        raise ValueError('Provide the exact image ID from the P105 producer')
    root=audit(release)
    output.mkdir(parents=True)
    context=output/'context';context.mkdir()
    try:
        os.link(release/'rootfs.tar.gz',context/'rootfs.tar.gz')
    except OSError:
        shutil.copy2(release/'rootfs.tar.gz',context/'rootfs.tar.gz')
    shutil.copy2(PROJECT/'desktop/p105/smoke-headless',context/'smoke-headless')
    (context/'Containerfile').write_text('FROM '+builder_image+' AS tools\nFROM scratch\n'
        'ADD rootfs.tar.gz /\nCOPY --from=tools /usr/libexec/omarchy-build /usr/libexec/omarchy-build\n'
        'COPY --chmod=0755 smoke-headless /usr/libexec/omarchy-build/smoke-headless\n'
        'ENTRYPOINT ["/usr/libexec/omarchy-build/with-arm"]\n')
    image_id=output/'test-image.id'
    with (output/'image-build.log').open('w') as log:
        subprocess.run(['podman','build','--iidfile',str(image_id),'-f',str(context/'Containerfile'),str(context)],
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    image=image_id.read_text().strip()
    container='p105-desktop-test-'+secrets.token_hex(8)
    command=['podman','run','--name',container,'--privileged','--network','none','-e','QEMU_CPU=cortex-a9',image,
        '/bin/bash','--noprofile','--norc','-c',
        'dbus-uuidgen > /etc/machine-id; exec runuser -u tablet -- python '
        '/usr/libexec/omarchy-build/smoke-headless --stage / --output /tmp/p105-desktop-validation']
    with (output/'desktop.log').open('w') as log:
        process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    subprocess.run(['podman','cp',container+':/tmp/p105-desktop-validation',str(output/'evidence')],check=True)
    subprocess.run(['podman','rm',container],check=True,stdout=subprocess.DEVNULL)
    evidence=json.loads((output/'evidence/result.json').read_text())
    result={'schema':1,'profile':'p105','architecture':'armv7h','physical_hardware':False,
            'root_sha256':root['root']['sha256'],'passed':process.returncode==0 and evidence.get('passed') is True,
            'test_image':image,'exit':process.returncode}
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result['passed']:
        raise RuntimeError('P105 artifact desktop failed; inspect '+str(output/'evidence'))
    print('Verified finished P105 desktop artifact:',output)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--builder-image',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    smoke(args.release,args.builder_image,args.output)


if __name__=='__main__':
    main()
