# iPhone 6 RAM boot

This experiment prepares an Orchard USB shell for `iPhone7,2` / N61AP, A8
T7000, with CPID `0x7000` and board ID `0x06`. Its local `orchard.toml`
selects the `n61` hardware descriptor and `apple-4k` kernel platform.

The first physical boot passed on 28 October 2026. The USB root shell
reported `7.3.0-rc1-orchard-apple-4k` with 4 KiB pages and both Typhoon CPUs
online. Linux text was visible on the 750 × 1334 LCD through simpledrm.

That boot used PongoOS `2.6.3-e98323f8` bundled in official palera1n v2.4.
Its 238,104-byte image has SHA-256
`5475c5f701423858b34e92176c966a9d4b12950f38acb8d1c347f14d5b272655`.
The default source-built Pongo's A8 entry remains under investigation.
Use the verified bundled image to reproduce the recorded boot.

From the Omarchy A checkout, build before entering DFU, supplying that
Pongo image through the existing component override:

```sh
./orchard build examples/n61-ram --pongo /path/to/Pongo-2.6.3-e98323f8.bin
```

The hardware and CLI sources must contain N61 support. On macOS, place Linux
source and compiler scratch on a case-sensitive filesystem. The shared
producer uses the pinned Linux revision and patch series, then assembles
BusyBox and this directory's `/init` through the usual RAM builder.

Keep the iPhone 6 as the only connected 64-bit iOS device. The recorded
test preserved a connected 32-bit iPad mini in normal iOS. Enter a fresh
DFU session using palera1n's guided countdown, then run the upload:

```sh
./orchard run examples/n61-ram
```

Inspect the displayed model and identity before confirming. Orchard verifies
the payload and uploads once through the shared Pongo transport. On an
Apple Silicon Mac using USB-C, watch `examples/n61-ram/out/palera1n.log` live and reconnect
the phone's Lightning plug immediately after `Checkmate!`. The recorded
successful attempt reached download mode three seconds after that cue.

After upload, run `./orchard devices` and find the `Orchard n61-ram`
product. macOS IOKit can present its name as `Orchard n61_ram`. Use that
device's `serial_port` value to connect to the USB shell.

The experiment mounts pseudo-filesystems, checks `apple,n61` and exposes an
ACM root shell. Its USB descriptor carries the current boot ID. Automatic
module loading stays disabled, and the image leaves internal storage inactive.

At the shell, record the kernel and page size:

```sh
uname -a
grep -m 1 KernelPageSize /proc/self/smaps
cat /sys/devices/system/cpu/online
tr '\000' '\n' </proc/device-tree/compatible
cat /proc/mtd
ls -l /sys/class/block
```

Capture the serial log and the build receipt together. Page size should be
4 KiB, with both Typhoon CPUs online. Classify each reported MTD or block
device by its backing driver before interpreting the inventory. A RAM region
used for the Apple Device Tree can appear separately from flash storage.

One successful RAM boot is recorded. Further qualification requires repeated
boots and a recorded return to iOS after a successful Linux session.
The build receipt starts with `hardware_tested=false`; USB upload completion
leaves Linux readiness for the serial check. Installation remains disabled
in the N61 descriptor while storage and peripheral work continues.
