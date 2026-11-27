#!/usr/bin/env python3
"""orchard build's entry (orchard.toml [release]): every component of a release, then the release.

orchard runs it as `tools/build.py --version VERSION --output DIRECTORY
[--platform NAME ... | --platform all] [--architecture aarch64|armv7h]` in this checkout. A release
has one root of one architecture: the selected platforms' (apple-armv7: armv7h), else
--architecture, else aarch64. Components land in out/components/NAME/KEY/, keyed by the
files they are made from and the architecture, so a build redoes only what changed: a shell edit
rebuilds the omarchy-a package and the root, not the artwork. The one package built here is
omarchy-a, this checkout's own files, with the Orchard package repository's recipe
(release/package.py); the root installs it, and Mesa, wlroots, Labwc and the rest from that
repository's [orchard] (system/assemble-rootfs, system/orchard-packages.txt). With a checkout
of that repository (ORCHARD_PACKAGES, which orchard build --packages or packages in
orchard.local.toml sets, or --packages DIR), those whose recipe there is not the published one
are built from it with its own container build (ci/build-package) and installed instead, and
omarchy-a's recipe comes from it too. orchard supplies its
m1n1, Pongo, the static tools and every platform's kernel
(python -m orchard.inputs); its producers run as commands from the orchard
snapshot (ORCHARD_CHECKOUT, which orchard build sets, or --orchard DIR) and
none of its Python is imported (orchard docs/distribution-contract.md). The
release itself is always assembled anew.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from components import component  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from release.architecture import platform_arch, validate  # noqa: E402
from release.package import version as package_version, recipe as fetch_recipe  # noqa: E402
DESKTOP_IMAGE = ['desktop/Containerfile', 'desktop/install-toolchain', 'desktop/snapshot_buildenv.py']
# What each component is made from, relative to this checkout.
INPUTS = {
    # Everything the omarchy-a package is made from: the whole tree but the image's own parts.
    'package': ['Makefile', 'desktop', 'system/overlay', 'release/package.py', 'release/architecture.py'],
    'base': ['system/build-rootfs', 'system/assemble-rootfs', 'system/Containerfile',
             'system/install-toolchain', 'system/packages.txt', 'system/orchard-packages.txt', 'system/rank-mirrors',
             'system/pacman-download', 'release/architecture.py'],
    'artwork': ['boot/build-artwork', 'boot/generate-logo.py', 'boot/splash.py', 'boot/artwork'],
}


# The ARMv7 Arch Linux ARM builder system/build-armv7-builder prepares; it runs ARMv7 code (emulated on arm64).
ARMV7_BUILDER = 'localhost/omarchy-a-arch-builder:armv7h'


def run(*argv):
    print('+', ' '.join(map(str, argv)), flush=True)
    subprocess.run([str(part) for part in argv], cwd=PROJECT, check=True)


def python(*argv):
    run(sys.executable, *argv)


def orchard_command(module, *argv):
    """orchard's producer MODULE as a command from the snapshot (PYTHONPATH=SNAPSHOT/src).

    Under the orchard tool's build (ORCHARD_TOOL names it) the tool resolves the
    inputs itself: the same arguments and the same document, with paths into its cache.
    """
    root = Path(os.environ['ORCHARD_CHECKOUT'])
    if module == 'orchard.inputs' and os.environ.get('ORCHARD_TOOL'):
        command = [os.environ['ORCHARD_TOOL'], 'inputs', *map(str, argv)]
    else:
        command = [sys.executable, '-m', module, *map(str, argv)]
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, cwd=PROJECT, check=True, env={**os.environ, 'PYTHONPATH': str(root / 'src')})


def targets(orchard, requested, architecture=None):
    """Select one userspace architecture before producing any component."""
    if 'all' in requested and len(requested) != 1:
        raise ValueError('--platform all builds every matching platform and combines with no other')
    explicit = requested if requested != ['all'] else []
    names = list(explicit) if explicit else [p.stem for p in sorted((orchard / 'platforms').glob('*.toml'))]
    found = {name: platform_arch(name, orchard) for name in names}
    selected_arch = validate(architecture or (found[names[0]] if explicit else 'aarch64'))
    if explicit and any(arch != selected_arch for arch in found.values()):
        raise ValueError('A release must use one userspace architecture; build ARMv7 and AArch64 separately')
    selected = [name for name, arch in found.items() if arch == selected_arch]
    if not selected:
        raise ValueError(f'No platforms build the {selected_arch} userspace')
    return selected_arch, selected


# What the packages checkout builds with besides a package's own recipe: its container build.
PACKAGES_BUILD = ['ci/build-package', 'ci/container', 'ci/container-build', 'ci/containers.json',
                  'ci/prepare-pacman', 'ci/tablet-repos', 'ci/rank-mirrors', 'ci/pacman-download']


def orchard_packages(architecture):
    """What the image takes from [orchard] on ARCHITECTURE (system/orchard-packages.txt)."""
    names = []
    for line in (PROJECT / 'system/orchard-packages.txt').read_text().splitlines():
        fields = line.split('#', 1)[0].split()
        if fields and (len(fields) == 1 or architecture in fields[1:]):
            names.append(fields[0])
    return names


def local_packages(checkout, architecture):
    """The image's [orchard] packages that CHECKOUT (OrchardLinux/packages) has another recipe of.

    Each is built with the checkout's own container build, as its CI builds
    it, after and against those of them it needs, into
    out/components/orchard-NAME/KEY/package/; KEY is its recipe (pin,
    patches, PKGBUILD), the checkout's build scripts and the keys of what it
    was built against, so an unchanged recipe is built once. Those the
    published repository has from the same recipe are not built: [orchard]'s
    are those. Returns {name: (package file, key)}, in build order.
    """
    names = orchard_packages(architecture)
    print('+', sys.executable, checkout / 'tools/pkgrepo', 'local', '--arch', architecture, *names, flush=True)
    try:
        plan = json.loads(subprocess.check_output(
            [sys.executable, str(checkout / 'tools/pkgrepo'), 'local', '--arch', architecture, *names], text=True))
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'{checkout}: its tools/pkgrepo local failed (a checkout from before local builds? '
                         'update it to OrchardLinux/packages main)') from error
    scripts = hashlib.sha256(b''.join(name.encode() + b'\0' + (checkout / name).read_bytes()
                                      for name in PACKAGES_BUILD)).hexdigest()
    built = {}
    for row in plan['packages']:
        name = row['name']
        if not row['build']:
            print(f'{name} {row["version"]}: the published package is this recipe\'s', flush=True)
            continue
        print(f'{name} {row["version"]}: built from {checkout} (published: {row["published"] or "none"})', flush=True)
        against = {need: built[need][1] for need in row['needs'] if need in built}

        def produce(path, work, name=name, row=row, done=dict(built)):
            # The ones built before: the build takes them ahead of the published [orchard].
            repo = work / 'local'
            if repo.exists():
                shutil.rmtree(repo)
            repo.mkdir()
            for file, _ in done.values():
                shutil.copy2(file, repo / file.name)
            path.mkdir()
            print('+', 'OUT=' + str(path), 'LOCAL_REPO=' + str(repo), checkout / 'ci/build-package', 'arch', name,
                  architecture, row['version'], flush=True)
            subprocess.run([str(checkout / 'ci/build-package'), 'arch', name, architecture, row['version']],
                           cwd=checkout, check=True,
                           env={**os.environ, 'OUT': str(path), 'LOCAL_REPO': str(repo),
                                'PACKAGER': 'OrchardLinux packages (local build)'})
            if len(list(path.glob('*.pkg.tar.zst'))) != 1:
                raise ValueError(f'{name}: the build made no single package')
        directory, key = component(PROJECT, 'orchard-' + name, [], produce, artifact='package',
                                   extra=[name, row['version'], row['recipe'], architecture, scripts,
                                          json.dumps(against, sort_keys=True)])
        built[name] = (next(directory.glob('*.pkg.tar.zst')), key)
    return built


def builder_key(image):
    if not image:
        return ''
    if os.environ.get('ORCHARD_BUILD_NATIVE') == '1':
        return 'native:' + image
    return subprocess.check_output(['podman', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--platform', action='append', default=[],
                        help='build this platform (repeat), or all; orchard passes the selection')
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    parser.add_argument('--packages', type=Path, help='a checkout of OrchardLinux/packages: build the image\'s '
                        '[orchard] packages whose recipe there is not the published one (default: ORCHARD_PACKAGES)')
    parser.add_argument('--architecture', choices=('aarch64', 'armv7h'),
                        help="the root's architecture (default: the selected platforms', else aarch64)")
    parser.add_argument('--builder-image', help='prepared Arch Linux ARM desktop/root builder for the selected architecture')
    args = parser.parse_args()
    orchard = args.orchard or (Path(os.environ['ORCHARD_CHECKOUT']) if os.environ.get('ORCHARD_CHECKOUT') else None)
    if orchard is None or not (orchard / 'src/orchard').is_dir():
        parser.error('Name the orchard snapshot: --orchard DIR, or ORCHARD_CHECKOUT (orchard build sets it)')
    # Every step below, the desktop recipes included, finds orchard here.
    os.environ['ORCHARD_CHECKOUT'] = str(orchard.resolve())
    packages = args.packages or (Path(os.environ['ORCHARD_PACKAGES']) if os.environ.get('ORCHARD_PACKAGES') else None)
    if packages is not None and not (packages / 'tools/pkgrepo').is_file():
        parser.error(f'{packages} is not a checkout of OrchardLinux/packages')
    try:
        architecture, platforms = targets(orchard, args.platform, args.architecture)
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))
    # orchard.inputs resolves every arm64 platform when it is given none; the 32-bit ones are named.
    named = [name for name in args.platform if name != 'all'] or ([] if architecture == 'aarch64' else platforms)
    selected = [part for name in named for part in ('--platform', name)]
    target_args = ['--architecture', architecture]
    if architecture == 'armv7h' and not args.builder_image:
        args.builder_image = ARMV7_BUILDER  # what system/build-armv7-builder prepares
    builder_args = ['--builder-image', args.builder_image] if args.builder_image else []
    identity = builder_key(args.builder_image)

    # This checkout as the omarchy-a package, made with the Orchard package
    # repository's recipe (OMARCHY_A_RECIPE: a checkout's packages/omarchy-a/arch), so the
    # image carries what this commit is. A changed recipe makes a new package.
    pkgver = package_version()
    recipe = PROJECT / 'out/components/.recipe'
    if recipe.exists():
        shutil.rmtree(recipe)
    if packages and not os.environ.get('OMARCHY_A_RECIPE'):
        fetch_recipe(recipe, packages / 'packages/omarchy-a/arch')  # the packages checkout's recipe
    else:
        fetch_recipe(recipe)
    recipe_key = hashlib.sha256(b''.join((recipe / name).read_bytes() for name in sorted(os.listdir(recipe)))).hexdigest()
    package, package_key = component(PROJECT, 'package', INPUTS['package'],
        lambda path, work: python('-m', 'release.package', '--output', path, '--recipe', recipe,
                                  *target_args, *builder_args),
        artifact='package', extra=[recipe_key, pkgver, architecture, identity])
    # The [orchard] packages a packages checkout has other recipes of, built from it.
    built = local_packages(packages.resolve(), architecture) if packages else {}
    local_args, local_extra = [], []
    if built:
        staged = PROJECT / f'out/components/.orchard-packages-{architecture}'
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        for file, _ in built.values():
            os.link(file, staged / file.name)
        local_args = ['--local-packages', staged]
        local_extra = [json.dumps({name: key for name, (_, key) in built.items()}, sort_keys=True)]
    # The base names the component, not a release: it serves every build with the same inputs.
    base, _ = component(PROJECT, 'base', INPUTS['base'],
                        lambda path, work: run('system/build-rootfs', '--output', path, '--package', package,
                                               '--release', 'base-' + package_key[:16], *target_args, *builder_args,
                                               *local_args),
                        artifact='base', extra=[package_key, architecture, identity, *local_extra])
    # The Omarchy mark: the splash of the root, the logo of the release.
    artwork, _ = component(PROJECT, 'artwork', INPUTS['artwork'],
                           lambda path, work: python('boot/build-artwork', '--output', path), artifact='artwork')
    # What orchard supplies finished: kernels, loaders, tools (the nightly's when they match).
    inputs = PROJECT / f'out/components/.inputs-{architecture}.json'
    orchard_command('orchard.inputs', '--output', inputs, *selected)
    shared = json.loads(inputs.read_text())['shared']
    tools = shared['tools']
    python('-m', 'release.build', '--release', args.version, '--inputs', inputs,
           '--base', base / 'rootfs.tar.gz', '--base-receipt', base / 'rootfs.tar.gz.json',
           '--splash', artwork / 'splash', '--logo', artwork / 'logo.bin',
           *(part for name in ('busybox', 'dropbear', 'dropbearkey')
             for part in ('--' + name, tools[name])),
           *target_args, '--output', args.output)
    python('-m', 'release.audit', args.output / 'release.toml')
    # install.sh: installs the orchard command and runs `orchard install` for the index beside it.
    python(orchard / 'producers/install_script.py', '--name', 'Omarchy A', '--index', 'index.toml',
           '--url', 'install.sh', '--output', Path(args.output) / 'install.sh')


if __name__ == '__main__':
    main()
