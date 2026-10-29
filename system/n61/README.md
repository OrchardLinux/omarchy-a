# N61 Arch Linux ARM desktop

The N61 profile composes the shared AArch64 Omarchy desktop with its matching
`7.3.0-rc1-orchard-apple-4k` module tree. Its root runs from a private NFS export.
The hardware RAM handoff owns the USB gadget and preserves its network link.
NetworkManager leaves `usb0` unmanaged in the desktop.

On 28 October 2026, a physical iPhone 6 reached Arch Linux ARM with systemd 262.1
and the 4 KiB kernel through this NFS flow. The `tablet` session used PAM/logind
and user D-Bus to run Labwc and Quickshell. The owner confirmed the Omarchy
wallpaper and top bar; a 750×1333 compositor frame was retained. Systemd reported
zero failed units. Omacalc opened and calculated `2+2=4` through the host's
virtual keyboard helper.

On a later boot using the complete touch payload, the owner confirmed calculator
input and swipes. The capture recorded 50 contacts and 50 releases. On 29 October,
the reconciled build reached the desktop twice with distinct boot IDs. Touch
worked on both boots; the first covered y=26..1322 on the 0..1333 axis and
on-screen keyboard entry. The recorded payload SHA-256 was
`b2d49d60b3771947e11efcee4d1d7f91d126a333d7373bae02b4d1f341f6ec78`, and the
desktop archive SHA-256 was
`a6e0626dc02d8aff535d6c0fa8f14cb54954700bfda5f267528f07cec3d6fa57`.
The desktop requires the USB link and its NFS host for the whole session. Installing
Linux on the phone's storage and starting it after an untethered restart remain
future work.

Labwc uses Pixman. Qt Quick and Mesa use software rendering, and the nominal 750×1334
panel uses scale 1.5. The memory policy allocates half of `MemTotal` to zram,
capped at 512 MiB. Firefox starts with a two-process preference and a 16 MiB
memory cache. The compositor can start while physical input drivers are pending.
Memory pressure and browser use need further tests on the phone.
The image reuses the upstream package-keyring initialization and screen-toggle
helpers. N61 retains its tested zram service and 512 MiB cap; the upstream zram
generator has a separate policy that requires device testing before adoption.
The N61 backlight permission rule targets the T7000 DWI device-tree address;
physical screen-toggle and brightness checks remain open.

The demo session logs in as `tablet` and grants passwordless sudo. The public
archive contains desktop policy and public components; private NFS staging
creates the session identity and can provision an explicit owner SSH key.

Run the shared component producers from the development checkout with its
`.venv/bin` on `PATH`. Select the intended ARM64 Podman connection before builds.
Every output directory must be new.

```sh
python desktop/build --output out/n61-components/desktop
python desktop/build-cursor-helper --output out/n61-components/cursor
python desktop/build-bluetooth-tools --output out/n61-components/bluetooth
python desktop/build-labwc --output out/n61-components/labwc
bash system/build-rootfs n61 \
  --desktop out/n61-components/desktop --release n61-desktop-1 \
  --output out/n61-base
python -m release.n61.build \
  --base out/n61-base --modules-dir /path/to/coherent-kernel/lib/modules \
  --release n61-desktop-1 \
  --cursor-tools out/n61-components/cursor \
  --bluetooth-tools out/n61-components/bluetooth \
  --labwc-tools out/n61-components/labwc --output out/n61-release
python -m release.n61.audit out/n61-release
```

The release contains `rootfs.tar.gz`, its complete catalog, the package inventory,
the hardware kernel receipt as `kernel.json`, and `rootfs.json`. The producer
checks the receipt's device, platform, image, DTBs and complete module inventory.
It verifies the installed hardware recipe against the kernel receipt and records
the CLI and hardware package fingerprints. `--hardware` selects a matching
hardware checkout when its recipe differs from the installed package.
The auditor checks those module hashes alongside the AArch64 init,
software-rendering policy and privileged package metadata. J71b's installed
runtime and firmware activation policy stay outside this profile.

Prepare touch firmware privately on the host through the shared Orchard adapter.
The explicit profile selects N61 independently of the checkout's default device.
This first acquisition allows the pinned Apple IPSW download; later runs verify
and reuse the cached output. Choose a new mixin output directory each time.

```sh
uv run python - <<'PY'
from pathlib import Path
from orchard_cli.devices import load
from orchard_cli.progress import Clock, Progress

device = load('n61')
outputs = device.firmware_inputs(Clock(), Progress(), allow_download=True)
archive, receipt = device.prepare_mixin(outputs, Path('out/private/n61-firmware'))
print(archive)
PY
```

Set `allow_download=False` when using a prepared cache. The recipe verifies
`N61.mtprops` from iOS 12.5.1 build 16H22 and produces
`lib/firmware/apple/n61-fwstart.z2fw`. Unit calibration comes from the phone's ADT
at boot. Retain `mixin.tar.gz` and its sibling `mixin.json` together as private
inputs for NFS staging.

Expand the public release as root on a case-sensitive Linux filesystem dedicated to the N61
export. Staging retains numeric owners and checks the package privilege bits
after extraction. Absolute guest links become equivalent relative links so host
inspection stays inside the staged root.

```sh
python -m release.n61.prepare_nfs \
  --release out/n61-release --destination /srv/orchard/n61/root-1 \
  --firmware-mixin out/private/n61-firmware/mixin.tar.gz \
  --firmware-receipt out/private/n61-firmware/mixin.json \
  --authorized-key /path/to/owner-ed25519.pub
```

Supply both firmware options to include touch firmware in a private root.
Staging verifies the archive receipt,
N61 profile and every output hash against the installed hardware recipe before
writing firmware as root-owned mode 0600 files under `/usr/lib/firmware`.
The private staging receipt records the mixin hash and firmware inventory.
Public release artifacts keep their original hashes. The N61 touch driver has
passed physical contact, motion and release checks on the tethered desktop.
Use the complete module tree from the same native kernel component when
producing the N61 image; `apple_z2` is a module and needs the verified firmware
when it loads. The recorded touch boot applies to its matching kernel, DTB,
modules and firmware. A rebuilt combination needs its own physical checks.

Omit `--authorized-key` when the RAM rescue shell supplies diagnostics. With an
owner key, staging creates private host keys and enables key-only OpenSSH for
`root` and `tablet`; this option requires `ssh-keygen` on the staging host.
The keys remain in this private NFS root.

`/srv/orchard/n61/root-1/etc/orchard/nfs-root.json` binds a fresh UUID to the public
image and receipt hashes. Pass that exact file to
`python -m orchard_hardware.boot.initramfs.nfs.stage --receipt ...` when building
the native RAM experiment. Hardware verifies those bytes before handing off to
systemd. Keep the separate `root-1.private.json` staging receipt private.

The physical sessions qualify the recorded artifacts and inputs above. Later
kernel, firmware or desktop combinations need their own device checks.
