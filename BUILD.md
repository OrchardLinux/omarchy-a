# Build Omarchy A

## GitHub Actions

`.github/workflows/build.yml` runs unit tests on pull requests and `main`. Version tags (`v*`) and manual dispatches additionally build Pongo/artwork on macOS, m1n1 on Linux ARM64, and the signed Arch Linux ARM userspace on a native ARM64 worker using the same pinned Arch job image and `install-toolchain` recipes as local builds. Source packages build as an unprivileged user; rootfs package assembly runs as root in the disposable job. No nested Podman is used. Shared recipe path variables select actual CI paths instead of container mounts. Native execution is not a security or network sandbox.

`ci/dependencies` installs a hashed, published CLI/hardware wheel pair and verifies the compiled hardware bundle. Select immutable dependency tags during manual dispatch; tag builds use explicit defaults in the workflow. Hardware code comes from the wheel, not a sibling checkout or an implicit `main` branch.

Assembly runs the same producers, artifact auditor, CLI resolution and publication staging as local builds. Version tags create **draft** releases; manual builds only retain workflow artifacts for seven days. Nothing automatically announces a release or operates a device. Follow the [release order](https://github.com/OrchardLinux/hardware/blob/main/docs/ci.md), then qualify fresh installation and cold-restart launch on hardware.

## Local setup

Run commands from this repository. Requires uv, `zstd`, and a native ARM64 Podman
environment for image/component builds. Pongo builds additionally need macOS/Xcode.

## Set up build tools

```sh
./orchard --version
```

The launcher initializes missing CLI/hardware submodules and uv installs them
editable into the workspace environment. No activation, published wheel pair or
Orchard release is required for local development. Use `uv run python ...` for the
existing Python producers below, or the workspace interpreter selected by your
editor. CI's explicit published-input path remains unchanged.

The root `orchard.toml` selects the default hardware recipe with `device = "j71b"`.
RAM builds and automatic kernel resolution below use that setting.

## Produce components

- `desktop/build-sources` and `desktop/build`: desktop applications and payload.
- `system/build-rootfs`: signed Arch Linux ARM base and package receipt; see [system/j71b/README.md](system/j71b/README.md).
- Hardware supplies kernel, DTB, module and static BusyBox/Dropbear recipes; see [hardware build instructions](https://github.com/OrchardLinux/hardware/blob/main/BUILD.md). Local assembly automatically resolves the kernel/DTB/modules through Orchard's shared cache. Build the static tools separately; supply explicit kernel artifacts only when overriding that default.
- `python boot/build-loader`: distro-branded loader. Pongo sources and build instructions are under `boot/pongo/`.

Retain each component's receipt. Kernel, modules and DTB must be compatible. Do not change hardware activation or timing as part of presentation changes.

## Assemble

The following example uses distro-owned components collected under `out/components/`.
The omitted kernel/DTB/module inputs come from the same Orchard builder and cache
as `./orchard build examples/minimal-boot`. Matching inputs reuse the compiled
bundle without checking out or compiling Linux again. Loader/Pongo branding,
userspace and assembly remain owned by this repository.

```sh
uv run python -m release.j71b.build \
  --release 0.1.0-orchard.3 \
  --base out/components/base/rootfs.tar.gz \
  --base-receipt out/components/base/rootfs.tar.gz.json \
  --loader out/components/m1n1.bin \
  --pongo out/components/Pongo.bin \
  --busybox out/components/boot/busybox \
  --dropbear out/components/boot/dropbear \
  --dropbearkey out/components/boot/dropbearkey \
  --cursor-tools out/components/desktop/cursor-tools \
  --bluetooth-tools out/components/desktop/bluetooth-tools \
  --labwc-tools out/components/desktop/labwc-tools \
  --output out/releases/0.1.0-orchard.3
```

To use explicit artifacts instead, supply all three of `--kernel FILE`, `--dtbs DIRECTORY`
and `--modules-dir DIRECTORY`. The recovery carries the DTB of every device that
shares the kernel; m1n1 boots with the one matching the device. Partial overrides are rejected to avoid mixing
kernel bundles. That explicit path does not invoke the cached builder and remains
compatible with CI's published wheel/component inputs. The default cache respects
`XDG_CACHE_HOME` and `ORCHARD_CACHE_DIR`, just like RAM builds; no cache flag is needed.

Choose a new version and output directory for each build. Root builds first; recovery embeds its exact stream receipt, and the index is written last. Installed wheel resources supply hardware code and scripts. The installed root carries no Orchard device runtime: it boots directly from its own kernel-install boot entry.

## Validate without a device

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python -m release.j71b.audit out/releases/0.1.0-orchard.3/j71b-checkm8-pongo.toml
orchard resolve out/releases/0.1.0-orchard.3/index.toml
```

The auditor verifies compressed recovery contents, executable endpoints, integrity lists, root/recovery runtime equality, the embedded root receipt, desktop/privilege policy, loader framing, and absence of private session/firmware data.

Headless finished-artifact checks use Podman without network or device passthrough:

```sh
python -m release.j71b.smoke_desktop \
  --manifest out/releases/0.1.0-orchard.3/j71b-checkm8-pongo.toml \
  --output out/validation/desktop \
  --pointer-helper out/components/validation/wlrctl
python desktop/test-input --artifact-only \
  --manifest out/releases/0.1.0-orchard.3/j71b-checkm8-pongo.toml \
  --output out/validation/input \
  --pointer-helper out/components/validation/wlrctl
```

Choose new evidence directories. `wlrctl` is a test-only native AArch64 helper, not installed in the image; both tests can run without it. They use `localhost/orchard-hardware-kernel-toolchain:bookworm`, built from the hardware package's kernel Containerfile. Native SSH/NSS regression uses the Arch builder image from this repository's base producer.

`tools/with-source-denied --deny PATH [--allow INPUT_DIRECTORY] -- COMMAND...` optionally verifies that a command does not read a source checkout.

## Publish

Follow [Publishing Omarchy A](docs/releasing.md). Build/audit success is not physical-device qualification: test a fresh installation and a cold-restart `orchard launch` on supported hardware before announcing the release. The experimental desktop auto-logs in at boot and has no disk encryption; this is disclosed in the README and must not be described as a secure daily-use system.
