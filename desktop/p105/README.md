# P105 desktop staging

This directory stages Omarchy A's Labwc and Quickshell desktop for the original
iPad mini Wi-Fi, iPad2,5 / P105AP. It uses an Arch Linux ARM armv7h userspace and
the 768 x 1024 panel at scale 1.

Boot access, kernel drivers, firmware preparation and the P105 runtime are
supplied separately. The current local bring-up uses Cascadia and an NFS root
on the host. This desktop payload contains no Apple firmware or device
calibration.

## Build the keyboard

Run in an armv7h Arch Linux ARM build environment. Install the build dependencies:

~~~sh
pacman -S --needed base-devel python wayland libxkbcommon pango scdoc pkgconf patch
python desktop/p105/build-keyboard --output out/p105-keyboard
~~~

The recipe downloads the source archive pinned in desktop/sources.json, applies
the existing Omarchy A keyboard patch and checks the ELF32 hard-float ABI. It
retains the archive, patch, upstream license and a build receipt.

Omafox and Omacalc have armv7h recipes under packages/. Build both as an
unprivileged user:

~~~sh
python desktop/p105/build-apps --output out/p105-apps
~~~

The helper runs makepkg and Omacalc's upstream offscreen tests, retaining
source archives, package metadata and ABI checks. Sign the resulting local
packages with an explicitly trusted local build key before installing them
with pacman -U when LocalFileSigLevel requires signatures. The browser
extension staged below is the same pinned, signed XPI used by the existing
desktop.

## Build desktop support

After preparing the synchronized ARMv7h package snapshot, build the existing
pinned Labwc source with Omarchy A's Super-key patch and the startup cursor
helper. The same command prepares the pinned Python Bluetooth library:

~~~sh
python desktop/p105/build-support --output out/p105-support --jobs 2
~~~

Additional compiler dependencies are meson, ninja, wlroots0.20,
wayland-protocols, libsfdo, libxml2, glib2, cairo, librsvg, xcb-util-wm,
xorg-xwayland and gettext. The build retains source archives and licenses,
then records their hashes, compiler identity and complete package list.
It performs no package installation.

## Stage and verify

Check out Omarchy at the commit in desktop/upstream.lock before staging:

~~~sh
python desktop/p105/stage.py \
  --output out/p105-desktop \
  --upstream out/pinned-omarchy \
  --keyboard out/p105-keyboard/wvkbd-mobintl \
  --support out/p105-support \
  --keyboard-sha256 "$(sha256sum out/p105-keyboard/wvkbd-mobintl | cut -d' ' -f1)"
python desktop/p105/stage.py --verify out/p105-desktop
~~~

The target must be a new directory. Staging verifies the Omarchy commit and clean asset paths,
keyboard and support binary hashes/ABIs, and the pinned browser extension. The final manifest
covers the complete payload after the P105 overrides. Verify this directory
before merging it into a populated root filesystem.

The root builder must create the tablet user with UID 1000, set ownership of
/home/tablet, install the Arch packages and configure PAM/logind, user D-Bus
and seatd. The staged getty override starts that user's console session.
The login helper requires that session and starts Labwc with Pixman and Qt
Quick's software renderer. The staged payload supplies the source-built Labwc
binary and cursor helper, Bluetooth pairing agent, and a backlight observer.
Source-built Labwc must remain paired with its recorded wlroots ABI during
hardware qualification.

The active menu keeps Apps, theme/background selection, browser learning
links, About, the native display/network/Bluetooth/battery panels, and the
shutdown operation. Its receipt lists every retained and omitted
source entry. PC package installation, update/configuration tools and
Hyprland controls remain outside this profile. Suspend and hibernate stay
absent while their kernel contracts lack hardware qualification. Cascadia
currently powers off when asked to reboot, so the Reboot entry is also
absent. Starting Linux again requires the Mac boot flow.

The P105 stage adds a read-only keyboard visibility signal to the built-in
Network panel's scoped facade. This lets its password field regain focus
when the on-screen keyboard changes state. The callback returns a boolean
for that built-in entry; the shared desktop source stays unchanged.

The P105 override leaves volume, the side switch and Hold to Cascadia's
p105-keys service. Labwc maps KEY_HOMEPAGE / XF86HomePage to the application
grid. Cascadia's stock button daemon consumes Home events, so delivery to
the compositor requires an external runtime forwarder. The opt-in
--desktop-home forwarder lives in the hardware work outside this desktop
change. The user confirmed that physical Home opens the application grid
with that runtime forwarder installed.

The generic desktop readiness helper captures one compositor frame to
/dev/null and records its boot ID, shell PID and Wayland socket. It does not
write an image or announce an Orchard installation.

## Firefox defaults for 512 MiB

The P105 policy adds experimental defaults for Firefox 157. It disables
content-process prelaunch and new-tab preloading, sets the shared content
pool to two processes, and caps each isolated origin's pool at one process.
Startup and new tabs open blank, while the welcome page stays closed. The
policy keeps the packaged Omafox extension and existing unrelated settings.

Every preference uses Status: default with an explicit type, so user values
can override it. Site isolation and sandbox settings retain their original
values. Separate sites and Firefox's helper processes still consume memory;
the content-pool preferences provide no global process or memory cap.

Mozilla documents these controls in its
[Preferences policy](https://firefox-admin-docs.mozilla.org/reference/policies/preferences/),
[Firefox 157 process defaults](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_157_0_RELEASE/modules/libpref/init/all.js)
and [first-run behavior](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_157_0_RELEASE/browser/components/asrouter/docs/first-run.md).
The complete source pointers are in firefox-sources.json. Compare process
counts and memory on the iPad after restarting Firefox.

## Check the desktop in a build container

After merging the staged payload and installing its signed application
packages, run as an unprivileged user:

~~~sh
python desktop/p105/smoke-headless \
  --stage out/p105-desktop \
  --output out/p105-headless-check
~~~

The helper gives Labwc a temporary home and D-Bus session, creates a
768 x 1024 headless output and checks the actual shell IPC, application grid
and theme carousel. Its output includes screenshots and result.json. The
first thumbnail scan can delay the carousel, so the check waits for a
changed viewport. The emulated session uses a longer IPC ceiling; physical
response times require a separate check.

Hardware services, charging and input access must be verified on the iPad.

## Local physical qualification

The original iPad mini Wi-Fi, iPad2,5 / P105AP with an A5 and 512 MiB RAM,
ran this desktop as native Arch Linux ARM armv7h code on Cascadia Linux
6.12 through a USB/NFS root. A repeat boot reached graphical.target in
27.478 seconds. Both the system manager and tablet user manager reported
zero failed units after FUSE was built in, and the document portal ran.
The user confirmed touch input with 2 + 2 = 4 in Omacalc. Foot and Firefox
launched on the iPad.

The external kernel/runtime contract used systemd namespaces and cgroups,
built-in FUSE, uinput and a 256 MiB LZ4 zram device. Kernel builds, hardware
services and the Home forwarder are supplied outside this desktop change.
The user confirmed physical Home opens the application grid. Wi-Fi scanning
and association succeeded, with the password entered through the on-iPad UI.
Bluetooth pairing awaits a device test, and audio playback remains unverified.

One settled Firefox sample with three restored tabs showed 208 MiB RAM
available and 99 MiB logical swap in use. These values describe that saved
session and workload. Content-pool defaults retain separate site/helper
processes and provide no global memory cap.

## Scope

The payload reuses the actual Omarchy A shell, app grid, menus, theme scripts,
Labwc decorations and Wayland keyboard. The existing desktop port has a
limited Omarchy CLI. This staging path does not add the full desktop PC
installer or a persistent installation on the iPad's NAND.

Runtime packages also include inotify-tools, libvips, wl-clipboard and
imagemagick for device watching, theme thumbnails and image metadata.

This directory covers experimental desktop staging. Supported releases
require separate hardware/boot integration and further qualification.
Staging verification establishes file integrity and target ABI; the local
physical observations above cover the tested device and workload.


## Native Omarchy A root build

`system/p105/build` composes a clean ARMv7 root from signed Arch Linux ARM
packages. It builds the keyboard and desktop support in the same synchronized
package environment as Quickshell and Qt, then stages this profile. The
hardware overlay comes from the active hardware package. Private firmware and
calibration arrive from the owner's RAM recovery during NFS handoff.

```sh
uv run python system/p105/build --release YOUR_NEW_VERSION --output out/p105-build
uv run python -m release.p105.build --base out/p105-build/result --output out/p105-release
uv run python -m release.p105.audit out/p105-release
```

The generic `system/build-rootfs p105` entry accepts the same arguments with a
configured Python environment. `build-state.json` retains the image identity
and work volume; package and source receipts accompany the result. A manual
P105 workflow can retain the audited public artifact without publishing it.
Existing J71b producers keep their own build path.

An owner can expand a verified release on the NFS host with administrator
access to preserve UID/GID and executable modes:

```sh
sudo .venv/bin/python -m release.p105.prepare_nfs \
  --release out/p105-release --destination /absolute/new/nfs-root \
  --owner-inputs /private/p105/owner-inputs
```

Owner inputs are explicit files with hashes in `owner-inputs.json`. They can
supply the tablet's authorized SSH keys, an owner SSH host key and Wi-Fi
connection files. Keep this directory private. The prepared root has its own
private receipt and can be exported over NFSv3/TCP to `10.55.0.2`. Its path
belongs to the host's NFS configuration.

Boot the private RAM bundle with the companion Orchard CLI and select that
export:

```sh
./orchard --profile p105 boot /private/p105/boot/boot.toml \
  --nfs-root 10.55.0.1:/absolute/new/nfs-root
```

The Mac supplies the root for the entire desktop session. The native image
retains the 256 MiB LZ4 zram setup and software rendering policy. Bluetooth
pairing and audio playback await physical qualification. The slow touch and
intermittent calibration failure recorded during the recovery work remain
open hardware issues.


The NFS host must provide a case-sensitive filesystem. On macOS, a separate
case-sensitive APFS disk image can hold the prepared root while keeping the
working export available. Keep that image mounted for the entire session.
The preparer checks case sensitivity before extracting files.

An owner input receipt has this structure, with each digest computed from
its corresponding private file:

```json
{"schema": 1, "profile": "p105", "files": {"home/tablet/.ssh/authorized_keys": "SHA256_HEX"}}
```

The finished artifact can also run in a disposable headless Cortex-A9 test
container. The test adds its emulator and a temporary machine identity to
the validation container. The public archive retains its original bytes:

```sh
uv run python -m release.p105.smoke_desktop \
  --release out/p105-release \
  --builder-image "$(cat out/p105-build/work/builder-image.id)" \
  --output out/p105-desktop-check
```

The result records the audited root hash and whether the app grid and theme
carousel responded. Screenshots accompany the result. The P105 workflow runs
this check for manually requested root builds. Physical input and radio
behavior require their own device checks.

Candidate `0.1.1-p105.1` passed two native Orchard CLI boots on the original
iPad mini Wi-Fi. Physical Home and Omacalc worked, and the owner entered a
Wi-Fi password with the on-screen keyboard. The saved connection returned
after reboot. See [the P105 validation record](../../docs/p105-validation.md)
for the tested root hash and remaining issues.
