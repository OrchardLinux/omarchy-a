# P105 native desktop validation

The phase 4 contribution builds the original iPad mini Wi-Fi desktop through
Omarchy A's own producers. Its target is Arch Linux ARM `armv7h`, with the
P105 runtime supplied by hardware 0.1.11. A host supplies the NFS root for the
entire Linux session.

## Build and artifact checks on 27 October 2026

The candidate `0.1.1-p105.1` was assembled from the pinned official ARMv7
bootstrap and a synchronized set of signed Arch packages. The producer
checked detached package signatures and retained the repository databases,
resolved package records and package inventory. Source builds ran as an
unprivileged account inside the disposable build environment.

| Check | Result |
| --- | --- |
| Runtime architecture | ARM ELF32 hard float for the desktop and systemd |
| Desktop components | Rebuilt keyboard, Labwc 0.20.2, cursor helper, Omafox and Omacalc |
| ABI pairing | Labwc and wlroots 0.20.2 from the same package snapshot |
| Clean root | 81,542 archive members; 2.29 GiB expanded file data |
| Public artifact | Complete catalog and compatibility receipt verified |
| Owner data | Separate scan passed over 65,666 regular files using the known private inputs |
| Finished-root desktop | Headless Cortex-A9 session passed at 768 × 1024 and scale 1 |
| Desktop interaction | App grid and theme carousel responded; screenshots retained |
| Experimental privilege policy | UID 1000 `tablet`, automatic console login and passwordless sudo; package sudo ownership and mode preserved |

The headless test runs the finished archive in its own disposable container.
Its temporary emulator and machine identity remain in that validation
container. Initial checks through a nested emulated chroot hit a QEMU crash;
direct execution of the artifact passed. The public root's archive bytes
remain unchanged by validation.

The Omarchy A suite runs 95 tests on Python 3.9.6 and 3.14.6, with 91 passing
and four skipped on this host. The merged CLI
passes 225 tests on both versions. Minimal Linux's merged suite passes 56.
The editable workspace starts with the compatible P105 dependency pair.

## Source and upstream integration

The desktop profile came from the source preserved during phase 1. Original
checkout heads and Git status still match that snapshot. The contribution
starts at Omarchy A main `3d1a09d4b1`; CLI and Minimal Linux integrate their
latest shared-cache and experimental RAM workflow changes. Their local P105
commits supply the workspace submodule pins. Publish those companion commits
before publishing parent commits that reference them.

Existing README text is preserved. README changes add the P105 sections and
instructions. J71b keeps its producer and release path; a separate P105
workflow checks the profiles and can build the NFS artifact on manual dispatch.

## Physical qualification

The candidate booted twice on the original iPad mini Wi-Fi through the installed
Orchard CLI and its NFS handoff. Each test started from iOS after a clean Linux
shutdown and had a distinct Linux boot identity. All five source checkouts and
the old workspace were denied to the host Python process during both boots.
The new root lives on a separate case-sensitive host image. The prior working
export is retained.
Owner Wi-Fi and SSH inputs were applied privately after the public archive
passed its audit.

| Device check | Measured result |
| --- | --- |
| Running system | Arch Linux ARM, `armv7l`, kernel `6.12.0`, release `0.1.1-p105.1` |
| Root and packages | New native NFS root; package inventory exactly matches the release |
| System and user managers | Zero failed units on both boots |
| Hardware runtime | Platform, touch, keys and zram active on both boots; all eight payload checks passed each time |
| Recovery | One USB serial reader in the current root on each boot; rescue executable verified in RAM |
| Storage fence | Flash controller disabled and MTD inventory empty on both boots |
| Desktop | Physical 768 × 1024 frames captured with the complete shell after both boots |
| Owner input | Home opened the app grid; Omacalc displayed 4 for 2 + 2 during the first session |
| Network password | Owner entered the password with the on-screen keyboard and connected during the first session |
| Network access | Saved Wi-Fi reconnected after reboot; certificate-verified HTTPS passed in each session |
| LAN SSH | Existing host identity and authorized owner key worked for `tablet` after both boots; sudo passed |

The shell took time to finish drawing after system services reported ready,
with partial bars visible in the first captures.

Touch latency and the intermittent calibration startup failure from the earlier
hardware qualification remain open. Both native desktop boots started their
touch service without intervention. Automatic time synchronization remains
open; `systemd-timesyncd` was inactive in the first session. Bluetooth pairing and audio playback
await their own device tests.

The tested public root has SHA-256
`66de9098b3b12caccc3ca21d2e8b5b3723afecfeded75a8cce5acc95e53f4e0c`.
Its local qualification receipt records the device results against that hash.
The producer marks each newly built candidate as awaiting physical testing.

Build receipts and test evidence remain in the owner's local phase 4 directory.
See [the P105 build instructions](../desktop/p105/README.md).
