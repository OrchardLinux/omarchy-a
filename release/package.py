#!/usr/bin/env python3
"""The omarchy-a package of this checkout, for an image: the Orchard package repository's recipe, run here.

Everything this repository puts on a tablet is the omarchy-a package. Its
recipe is the Orchard package repository's (OrchardLinux/packages,
packages/omarchy-a/arch): a plain PKGBUILD that builds a release tarball of
this repository with makepkg alone, `make` and `make install` (Makefile,
desktop/install-tree), with the pinned sources in its source=() array. A
release reaches [orchard] when the recipe moves to its tag; a tablet takes it
with `pacman -Syu` (or omarchy-update).

An image carries the package of its own commit: this runs that recipe's
makepkg in the desktop's builder on a tarball of this checkout in place of the
release's, so the image and a tablet updating get files made the same way.

    python3 -m release.package --output DIR [--architecture ARCH] [--recipe DIR]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

from release.architecture import validate, podman_arch

PROJECT = Path(__file__).resolve().parents[1]
# The recipe's two files, as the Orchard package repository has them on main;
# --recipe DIR (or OMARCHY_A_RECIPE) names a checkout's packages/omarchy-a/arch instead.
RECIPE_URL = 'https://raw.githubusercontent.com/OrchardLinux/packages/main/packages/omarchy-a/arch/'
RECIPE_FILES = ('PKGBUILD', 'omarchy-a.install')
NAME = 'omarchy-a'
def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('Unsafe package path')
    return str(path)


def version(project=PROJECT):
    """The release this tree is or follows: its newest release tag (v0.3.1 -> 0.3.1).

    A build between two releases has the version of the last one; the
    published package is only ever a release's. OMARCHY_A_VERSION overrides
    it, for a tree without git history (the recipe passes its pkgver).
    """
    value = os.environ.get('OMARCHY_A_VERSION')
    if not value:
        try:
            tag = subprocess.check_output(
                ['git', '-C', str(project), 'describe', '--tags', '--abbrev=0', '--match', 'v[0-9]*', 'HEAD'],
                text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise ValueError('No release tag in the git history (a shallow clone?); set OMARCHY_A_VERSION') from error
        value = tag.removeprefix('v')
    value = value.replace('-', '.')
    if not re.fullmatch(r'[A-Za-z0-9._+]+', value) or value.startswith('.'):
        raise ValueError('Invalid package version: ' + value)
    return value


def source_date(project=PROJECT):
    try:
        return subprocess.check_output(['git', '-C', str(project), 'log', '-1', '--format=%ct'],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return '0'


def package_info(path):
    """.PKGINFO of a built package, as {key: [values]}."""
    data = subprocess.run(['bsdtar', '-xOf', str(path), '.PKGINFO'], check=True, capture_output=True).stdout
    info = {}
    for line in data.decode().splitlines():
        if ' = ' in line and not line.startswith('#'):
            key, value = line.split(' = ', 1)
            info.setdefault(key, []).append(value)
    return info


def recipe(directory, source=None):
    """The recipe into DIRECTORY, from SOURCE (a checkout's packages/omarchy-a/arch) or the package repository's main."""
    from urllib.request import urlopen
    directory.mkdir(parents=True)
    source = source or os.environ.get('OMARCHY_A_RECIPE')
    for name in RECIPE_FILES:
        if source:
            data = (Path(source) / name).read_bytes()
        else:
            with urlopen(RECIPE_URL + name, timeout=60) as response:
                data = response.read()
        (directory / name).write_bytes(data)
    return directory / 'PKGBUILD'


# What a tarball of this checkout leaves out: history, build output, caches.
EXCLUDE = {'.git', 'out', 'build', '.venv', '.orchard', '__pycache__', '.work', '.DS_Store'}


# The name the checkout's tarball stands in under for the recipe's _commit.
CHECKOUT = 'checkout'


def tarball(path, project=PROJECT):
    """This checkout as the recipe's release archive has it (omarchy-a-checkout/...), uncommitted changes included."""
    import tarfile

    def keep(member):
        parts = Path(member.name).parts[1:]
        if any(part in EXCLUDE or part.startswith('.venv') or part.endswith('.pyc') for part in parts):
            return None
        member.uid = member.gid = 0
        member.uname = member.gname = 'root'
        return member
    with tarfile.open(path, 'w:gz') as archive:
        archive.add(project, arcname=f'{NAME}-{CHECKOUT}', filter=keep)
    return sha(path)


def local_recipe(text, pkgver, digest):
    """The recipe for this checkout: its version, and its tarball as the release archive (the first source)."""
    replaced = {}
    lines = []
    for line in text.splitlines():
        for key, value in (('pkgver=', f'pkgver={pkgver}'), ('_commit=', f'_commit={CHECKOUT}'),
                           ('source=(', f'source=("{NAME}-${{_commit}}.tar.gz"'),
                           ('sha256sums=(', f"sha256sums=('{digest}'")):
            if line.startswith(key):
                if key.endswith('(') and not re.match(re.escape(key) + r"""["'][^"']+["']\s*$""", line):
                    raise ValueError(f'The recipe\'s first {key} entry is not alone on its line')
                line = value
                replaced[key] = replaced.get(key, 0) + 1
        lines.append(line)
    if replaced != {'pkgver=': 1, '_commit=': 1, 'source=(': 1, 'sha256sums=(': 1}:
        raise ValueError('The recipe has no single pkgver, _commit, source and sha256sums to build this checkout with')
    return '\n'.join(lines) + '\n'


MAKEPKG = r"""
set -euo pipefail
export PKGDEST="$ORCHARD_WORK/out" BUILDDIR="$ORCHARD_TMP/build" SRCDEST="$ORCHARD_TMP/sources"
export PKGEXT=.pkg.tar.zst CARCH="$OMARCHY_CARCH" HOME="$ORCHARD_TMP"
mkdir -p "$PKGDEST" "$BUILDDIR" "$SRCDEST"
cd "$ORCHARD_WORK/recipe"
if [[ $(id -u) == 0 ]]; then
  # Native CI runs as root, which makepkg refuses.
  id omarchy-a-builder >/dev/null 2>&1 || useradd --system --no-create-home omarchy-a-builder
  chown -R omarchy-a-builder "$ORCHARD_WORK" "$ORCHARD_TMP"
  # The scratch directory around ORCHARD_TMP is root's and private: the
  # builder must be able to get through it to its own directories.
  chown omarchy-a-builder "$(dirname "$ORCHARD_TMP")"
  runuser -u omarchy-a-builder -- makepkg --nodeps --noconfirm
else
  makepkg --nodeps --noconfirm
fi
"""


def build(output, architecture='aarch64', builder_image=None, recipe_source=None, pkgver=None):
    """The package of this checkout in OUTPUT: the recipe's makepkg on a tarball of this tree."""
    validate(architecture)
    sys.path.insert(0, str(PROJECT / 'desktop'))
    from snapshot_buildenv import buildenv
    from target import builder
    if output.exists():
        raise ValueError('Choose a new package output directory')
    pkgver = pkgver or version()
    image = builder(buildenv, architecture, builder_image)
    work_parent = PROJECT / 'out/.package-work'
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='package-', dir=work_parent) as temporary:
        work = Path(temporary)
        pkgbuild = recipe(work / 'recipe', recipe_source)
        text = pkgbuild.read_text()
        # The recipe fetches upstream Omarchy at the commit this checkout's port follows.
        lock = dict(line.split('=', 1) for line in (PROJECT / 'desktop/upstream.lock').read_text().splitlines()
                    if '=' in line)
        if lock['omarchy_commit'] not in text:
            raise ValueError('The recipe pins another upstream Omarchy than desktop/upstream.lock')
        digest = tarball(work / 'recipe' / f'{NAME}-{CHECKOUT}.tar.gz')
        pkgbuild.write_text(local_recipe(text, pkgver, digest))
        buildenv.run(image, ['bash', '-euc', MAKEPKG], [(work, '/work', False)],
                     env={'OMARCHY_CARCH': architecture, 'SOURCE_DATE_EPOCH': source_date(),
                          'PACKAGER': 'Omarchy A <https://github.com/OrchardLinux/omarchy-a>'},
                     arch=podman_arch(architecture), network=True)
        built = sorted((work / 'out').glob('*.pkg.tar.zst'))
        if len(built) != 1:
            raise ValueError('makepkg made no single package')
        info = package_info(built[0])
        if (info.get('pkgname'), info.get('arch')) != ([NAME], [architecture]) or \
                not info.get('pkgver', [''])[0].startswith(pkgver + '-'):
            raise ValueError('The built package is not the planned one: ' + json.dumps(info))
        result = work / 'result'
        result.mkdir()
        package = result / built[0].name
        shutil.copyfile(built[0], package)
        receipt = {'schema': 1, 'name': NAME, 'version': info['pkgver'][0], 'architecture': architecture,
                   'file': package.name, 'bytes': package.stat().st_size, 'sha256': sha(package),
                   'depends': info.get('depend', [])}
        (result / 'package.json').write_text(json.dumps(receipt, indent=2) + '\n')
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(result, output)
    print('omarchy-a package:', output / receipt['file'])
    return receipt


def verify(directory, architecture=None):
    """DIRECTORY/package.json and the package it names; returns (receipt, package path)."""
    receipt = json.loads((directory / 'package.json').read_text())
    if receipt.get('schema') != 1 or receipt.get('name') != NAME:
        raise ValueError('Not an omarchy-a package receipt')
    if architecture and receipt.get('architecture') != architecture:
        raise ValueError('The omarchy-a package is of another architecture')
    package = directory / safe_name(receipt['file'])
    if package.is_symlink() or package.stat().st_size != receipt['bytes'] or sha(package) != receipt['sha256']:
        raise ValueError('The omarchy-a package differs from its receipt')
    return receipt, package


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path, help="the package of this checkout, with the recipe")
    action.add_argument('--verify', type=Path)
    action.add_argument('--print-version', action='store_true', help='print the version a build here has')
    parser.add_argument('--architecture', choices=('aarch64', 'armv7h'))
    parser.add_argument('--recipe', type=Path, help="a packages checkout's arch/omarchy-a (default: OMARCHY_A_RECIPE, "
                        "else the package repository's main)")
    parser.add_argument('--builder-image', help='existing Arch Linux ARM builder for the architecture')
    args = parser.parse_args()
    try:
        if args.print_version:
            print(version())
        elif args.verify:
            _, package = verify(args.verify, args.architecture)
            print('Verified', package)
        else:
            build(args.output.resolve(), args.architecture or 'aarch64', args.builder_image, args.recipe)
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
