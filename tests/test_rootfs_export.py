"""The root producer must consume a complete container export stream."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
PODMAN = r'''#!/usr/bin/env python3
import json, os, signal, sys
args = sys.argv[1:]
with open(os.environ['EXPORT_CALLS'], 'a') as stream:
    stream.write(json.dumps(args) + '\n')
if args == ['info'] or args[:2] == ['volume', 'rm']:
    sys.exit(0)
if args[:2] == ['volume', 'create']:
    print(args[2])
    sys.exit(0)
if args[0] == 'run' and '/repo/system/assemble-rootfs' in args:
    sys.exit(0)
if args[0] == 'run' and 'tar' in args:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    with open(os.environ['EXPORT_ARCHIVE'], 'rb') as source:
        while data := source.read(16384):
            while data:
                data = data[os.write(1, data):]
    open(os.environ['EXPORT_DRAINED'], 'x').close()
    sys.exit(0)
sys.exit('Unexpected fixture Podman command: ' + repr(args))
'''


@unittest.skipUnless(shutil.which('bash') and shutil.which('tar') and shutil.which('python3'),
                     'bash, tar and Python are required for the export fixture')
class RootfsExportTests(unittest.TestCase):
    def run_export(self, change=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        project = root / 'project'
        (project / 'system').mkdir(parents=True)
        shutil.copy2(PROJECT / 'system/build-rootfs', project / 'system/build-rootfs')
        (project / 'desktop').mkdir()
        # This fixture exercises export and verification after desktop checking
        # and native assembly have succeeded, without starting a container.
        (project / 'desktop/build').write_text('#!/usr/bin/env python3\n')
        (project / 'desktop/build').chmod(0o755)
        desktop = root / 'desktop'
        (desktop / 'payload').mkdir(parents=True)
        (desktop / 'packages').mkdir()
        binary = root / 'bin'
        binary.mkdir()
        (binary / 'podman').write_text(PODMAN)
        (binary / 'podman').chmod(0o755)
        contents = b'root-fixture\n' * 8192
        lock = b'fixture 1\n'
        record = {'architecture': 'armv7h', 'release': 'export-fixture',
                  'bytes': len(contents), 'sha256': hashlib.sha256(contents).hexdigest(),
                  'packages_lock_sha256': hashlib.sha256(lock).hexdigest()}
        files = {'rootfs.tar.gz': contents, 'rootfs.tar.gz.json': json.dumps(record).encode(),
                 'packages.lock': lock}
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w', format=tarfile.GNU_FORMAT) as archive:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        # Legal padding larger than a pipe buffer exposes an extractor that
        # exits at the tar end marker before its producer finishes writing.
        data = buffer.getvalue().ljust(4 * 1024 * 1024, b'\0')
        if change == 'corrupt':
            data = data[:515] + bytes((data[515] ^ 1,)) + data[516:]
        elif change == 'truncated':
            data = data[:512 + len(contents) // 2]
        stream = root / 'export.tar'
        stream.write_bytes(data)
        drained, calls, output = root / 'drained', root / 'calls.jsonl', root / 'output'
        result = subprocess.run(['bash', str(project / 'system/build-rootfs'),
            '--output', str(output), '--desktop', str(desktop), '--release', 'export-fixture',
            '--architecture', 'armv7h', '--builder-image', 'export-fixture'], capture_output=True,
            text=True, timeout=20, env={**os.environ, 'ORCHARD_BUILD_NATIVE': '0',
                'PATH': str(binary) + os.pathsep + os.environ['PATH'],
                'EXPORT_ARCHIVE': str(stream), 'EXPORT_DRAINED': str(drained), 'EXPORT_CALLS': str(calls)})
        self.assertTrue(any(row[:2] == ['volume', 'rm']
                            for row in map(json.loads, calls.read_text().splitlines())))
        return result, output, drained, files

    def test_padded_export_is_drained_before_success(self):
        result, output, drained, files = self.run_export()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(drained.is_file(), 'The archive producer did not reach EOF')
        for name, expected in files.items():
            self.assertEqual((output / name).read_bytes(), expected)

    def test_corrupted_export_is_refused(self):
        result, output, _, _ = self.run_export('corrupt')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_truncated_export_is_refused(self):
        result, output, _, _ = self.run_export('truncated')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())
