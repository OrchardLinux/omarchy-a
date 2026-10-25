#!/usr/bin/env python3
"""Materialize native storage-tool hardlinks in a verified base archive."""
import argparse
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def normalize(archive, receipt):
    record = json.loads(receipt.read_text())
    original = sha(archive)
    if original != record['sha256'] or archive.stat().st_size != record['bytes']:
        raise ValueError('Base archive differs from its receipt')
    temporary = archive.with_name(archive.name + '.normalized')
    try:
        with tarfile.open(archive, 'r:gz') as source, temporary.open('xb') as raw, \
                gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='', compresslevel=1) as zipped, \
                tarfile.open(fileobj=zipped, mode='w|') as target:
            for entry in source:
                name = entry.name.removeprefix('./')
                if entry.islnk() and re.fullmatch(r'usr/(?:bin|sbin)/(?:blkid|sfdisk|mke2fs)', name):
                    with source.extractfile(entry) as stream:
                        data = stream.read(16 * 1024 * 1024 + 1)
                    if not data.startswith(b'\x7fELF') or len(data) > 16 * 1024 * 1024:
                        raise ValueError('Storage hardlink does not reference a bounded native executable')
                    entry = copy.copy(entry)
                    entry.type, entry.linkname, entry.size = tarfile.REGTYPE, '', len(data)
                    target.addfile(entry, io.BytesIO(data))
                else:
                    target.addfile(entry, source.extractfile(entry) if entry.isfile() else None)
        record.update(source_archive_sha256=original, sha256=sha(temporary), bytes=temporary.stat().st_size)
        os.replace(temporary, archive)
        receipt.write_text(json.dumps(record, indent=2) + '\n')
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    normalize(args.archive, args.receipt)
