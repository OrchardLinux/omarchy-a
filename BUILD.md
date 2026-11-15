# Build Omarchy A

## GitHub Actions

`.github/workflows/build.yml` runs unit tests on pull requests and `main`. Version tags (`v*`), manual dispatches and the nightly additionally generate the loader artwork on macOS, build m1n1 on Linux ARM64, and the signed Arch Linux ARM userspace on a native ARM64 worker using the same pinned Arch job image and `install-toolchain` recipes as local builds. No package is built: the image installs Mesa, wlroots, Labwc, the video bridge, Omafox, Omactivity and Files from the Orchard package repository (below). The job compiles only the keyboard and the cursor helper; rootfs package assembly runs as root in the disposable job. No nested Podman is used. Shared recipe path variables select actual CI paths instead of container mounts. Native execution is not a security or network sandbox.

The build jobs start beside the tests; assembly, and with it every draft release and preview, waits for the tests. One result is kept between runs in GitHub's cache: the boot artwork, per content of `boot/` (`boot-artwork-v1-…`), drawn on a Mac only when that changed; a newer ImageMagick or librsvg alone does not redraw it. Raise `v1` in the key to start from nothing.

`ci/dependencies` takes orchard from the published orchard release a build names (`nightly`, the default, is orchard's newest nightly): its tooling is that release's `orchard-source.tar.gz`, unpacked, and its kernels, loaders and tools are the component bundles beside it, each checked against the release's `SHA256SUMS`. A build checks out and compiles nothing of orchard. Only the tests clone orchard's `main` (`ORCHARD_REF`), to notice early what changes there, and a build from an orchard run whose release is not published yet (`hardware_run_id`) clones that release's tag. Select another release tag during manual dispatch. The release receipt records the exact orchard commit.

### Nightly

Every night at 04:30 UTC, after orchard's own nightly, the workflow compares what a nightly is made of with what the last one was built from: this repository's `main` commit, the orchard nightly it would take, and the Orchard package repository (the checksum of its index, `orchard.db`, which changes with every package published there). If none changed, the run ends in its first job and nothing is built. Otherwise it builds as for a release and publishes two pre-releases:

- `nightly-YYYYMMDD-COMMIT`: everything a release has (root image, manifests, `install.sh`, installer), plus `nightly.json`, the record of what it was built from. Kept 7 days; the newest always stays.
- `nightly`: only a pointer to the newest: `latest.json` (the same record) and that nightly's `install.sh`.

```sh
curl -fsSL https://github.com/OrchardLinux/omarchy-a/releases/download/nightly/install.sh | sh
```

installs the newest nightly; the same address under a dated name installs that one. Nightlies are untested on hardware and never GitHub's "latest" release, so the README's install command keeps installing the last version. A nightly links orchard's kernels and loaders from orchard's nightly instead of carrying copies, and orchard removes its nightlies after 14 days (its newest stays): an old nightly stops being installable then.

`ci/nightly` holds the decision and the record. What a nightly is made of is a list of named inputs (`--input NAME=VALUE` in the workflow's first job and where the nightly is recorded, today `orchard` and `packages`); one more there adds an input. A dispatch with `nightly` ticked builds and publishes a nightly from `main` whether or not anything changed; from another branch it builds under the nightly's name and publishes nothing.

Assembly runs the same producers, artifact auditor, CLI resolution and publication staging as local builds. Version tags create **draft** releases; nightly runs publish pre-releases (below); manual builds only retain workflow artifacts. Nothing automatically announces a release or operates a device. Follow the [release order](https://github.com/OrchardLinux/orchard/blob/main/docs/ci.md), then qualify fresh installation and cold-restart launch on hardware.

## With orchard

```sh
orchard build [--version VERSION]
```

builds a release into `out/releases/VERSION` (default `dev-DATE-TIME`) through
`tools/build.py`, the entry `orchard.toml` names: each component below is kept in
`out/components/NAME/KEY/`, keyed by its files, and rebuilt only when they
change; the release is assembled and audited every time. `orchard run` starts
the selected kernel on the attached device and `orchard install` installs the
release. `orchard build --platform apple-armv7` builds the 32-bit (armv7h)
release instead. The rest of this page describes the producer steps.

## Local setup

Run commands from this repository. Requires uv, `zstd`, and a native ARM64 Podman
environment for image/component builds.

## Set up build tools

```sh
orchard --version
```

`orchard` comes from orchard's launcher on your PATH and runs orchard's newest
nightly (`ORCHARD_VERSION` pins one); an orchard checkout's own `bin/orchard` runs
that checkout. This build imports none of orchard's Python: it runs orchard's
producers as commands from an orchard snapshot (orchard
[docs/distribution-contract.md](https://github.com/OrchardLinux/orchard/blob/main/docs/distribution-contract.md)),
which `orchard build` names in `ORCHARD_CHECKOUT`. Without orchard, set
`ORCHARD_CHECKOUT` (or pass `--orchard DIR`) to an orchard checkout or a
release's `orchard-source.tar.gz` unpacked, and run the steps below with any
Python 3.11.

## Produce components

- `desktop/build`: the desktop payload (the pinned Omarchy UI and this repository's files) and the keyboard, a patched wvkbd compiled from its pinned source.
- `system/build-rootfs`: signed Arch Linux ARM base and package receipt; see [system/README.md](system/README.md). It installs the platform's packages from the Orchard package repository; see [Packages](#packages).
- orchard supplies the kernel, DTBs and modules of every platform, its platform layer, and the static BusyBox/Dropbear recipes; see [orchard's build instructions](https://github.com/OrchardLinux/orchard/blob/main/BUILD.md). Local assembly builds or reuses each platform's kernel through orchard's shared cache. Build the static tools separately; supply explicit kernel bundles only when overriding that default.
- `python boot/build-artwork --output DIR`: the Omarchy mark: `splash` (480 px, painted for an installed boot entry) and `logo.bin` (256 and 128 px).
- No loader is built here: a release names orchard's loaders as orchard's index lists them (arm64: Pongo and m1n1).

Retain each component's receipt. Do not change hardware activation or timing as part of presentation changes.

## Packages

No package is built in this repository. The image's pacman takes a package from the first repository that lists it, in this order, during the build and on the installed tablet (`/etc/pacman.conf`):

1. `[orchard]`, the [Orchard package repository](https://github.com/OrchardLinux/packages), built once for every Orchard distribution: `mesa` (the OrchardLinux fork with the GPU driver; 64-bit), `wlroots0.20`, `labwc` (with the tablet patches), `libva-v4l2-request` (64-bit), `omafox`, `omactivity`, `folio-touch` (Files; 64-bit images, ARMv7 keeps Dolphin), and `omacalc` on ARMv7. Their sources, patches and recipes are there.
2. `[omarchy]`, upstream Omarchy's repository (64-bit only; upstream publishes nothing for ARMv7): Omacalc.
3. Arch Linux ARM's repositories: everything else.

`system/assemble-rootfs` installs all of them in one transaction and refuses an image in which one of the Orchard packages would come from elsewhere. `[orchard]` is not signed yet (`SigLevel = Optional TrustAll`); the comment marked `SIGNING` in `system/assemble-rootfs` is where that changes once its key exists. No package file is pinned or downloaded here any more.

A change to one of these packages is made in the packages repository and reaches tablets through `pacman -Syu` and the next image; the nightly notices the new index.

## Assemble

The following example uses distro-owned components collected under `out/components/`.
A release has one root of one userspace architecture, and the same shape for
both: the root as a block image (`root.blocks.zst`, `root.map.json`), its logo,
and orchard's platform layers, loaders and install tools, which
`orchard.image.platforms_index` supplies from orchard's index of that
architecture (`platforms.toml` for arm64, the separate 32-bit index for
armv7h). No recovery image is part of a release.
The kernels come from the same orchard builder and cache as `orchard build` in
orchard's examples; matching inputs reuse the compiled bundles. Boot artwork,
userspace and assembly remain owned by this repository; the m1n1 is orchard's.
First what orchard supplies finished, as one JSON file (kernel bundles, boards,
m1n1, Pongo, tools; the nightly's when they match):

```sh
PYTHONPATH=$ORCHARD_CHECKOUT/src python -m orchard.inputs --output out/inputs.json
python -m release.build \
  --release 0.1.0-orchard.3 \
  --inputs out/inputs.json \
  --base out/components/base/rootfs.tar.gz \
  --base-receipt out/components/base/rootfs.tar.gz.json \
  --splash out/components/artwork/splash \
  --logo out/components/artwork/logo.bin \
  --busybox out/components/boot/busybox \
  --dropbear out/components/boot/dropbear \
  --dropbearkey out/components/boot/dropbearkey \
  --cursor-tools out/components/desktop/cursor-tools \
  --bluetooth-tools out/components/desktop/bluetooth-tools \
  --output out/releases/0.1.0-orchard.3
```

To use a staged kernel bundle, pass `--kernel-dir PLATFORM=DIRECTORY` to
`orchard.inputs`. Select a subset there with `--platform PLATFORM`; the index
consumes that document's exact selection. `release.build --orchard-release TAG`
takes finished AArch64 files from a published Orchard build and accepts
`--platform PLATFORM` to select its layers. `--architecture armv7h` builds the
32-bit release; from a published build it names its platforms
(`--platform apple-armv7`). The cache respects `XDG_CACHE_HOME`
and `ORCHARD_CACHE_DIR`, just like RAM builds.

Choose a new version and output directory for each build. Root builds first,
then orchard's files and the block image; `release.toml` and the index are
written last. The cached base retains `base-<desktop-key>` in
`etc/ipadlinux/release`; `etc/orchard/release.json` identifies the final
release.

For the ARMv7 compiler and build, see
[ARMv7 desktop components](desktop/armv7/README.md). Building the armv7h
desktop and base runs ARMv7 code: the builder image needs a Podman connection
that executes ARM32 binaries (emulated on an arm64 host, 1 to 3 hours). The
release step itself runs only arm64 tools.

## Validate without a device

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python -m release.audit out/releases/0.1.0-orchard.3/release.toml
PYTHONPATH=$ORCHARD_CHECKOUT/src python -m orchard.manifests --verify-local out/releases/0.1.0-orchard.3/index.toml
```

The auditor checks the block image, map, logo, loaders and install tools, the
platform layers against their receipts and SHA256SUMS, desktop integrity,
package privileges, that the desktop helpers are of the root's architecture,
and the absence of private session and firmware data.

Headless finished-artifact checks use Podman without network or device passthrough:

```sh
python -m release.smoke_desktop \
  --manifest out/releases/0.1.0-orchard.3/release.toml \
  --output out/validation/desktop \
  --pointer-helper out/components/validation/wlrctl
python desktop/test-input --artifact-only \
  --manifest out/releases/0.1.0-orchard.3/release.toml \
  --output out/validation/input \
  --pointer-helper out/components/validation/wlrctl
```

Choose new evidence directories. `wlrctl` is a test-only native AArch64 helper, not installed in the image; both tests can run without it. They use `localhost/orchard-hardware-kernel-toolchain:bookworm`, built from the hardware package's kernel Containerfile. Native SSH/NSS regression uses the Arch builder image from this repository's base producer.

`tools/with-source-denied --deny PATH [--allow INPUT_DIRECTORY] -- COMMAND...` optionally verifies that a command does not read a source checkout.

## Publish

Follow [Publishing Omarchy A](docs/releasing.md). Build/audit success is not physical-device qualification: test a fresh installation and a cold-restart `orchard launch` on supported hardware before announcing the release. The experimental desktop auto-logs in at boot and has no disk encryption; this is disclosed in the README and must not be described as a secure daily-use system.
