# Warm restart on a tether-booted iPad

Restart is a Linux-to-Linux kexec. Once cold-booted with the resident PSCI loader,
updates and restarts do not require a Mac. This assembly is host-built and tested;
its peripheral port still needs an Orchard device flight.

The reusable module lives under `system/overlay/usr/lib/orchard-kexec`, with the
`orchard-kexec` command (`linux-a9-kexec` is a compatibility alias). It imports no
Orchard CLI or image-builder Python. Other distributions can install the same
module, Python 3, kexec-tools, kmod, coreutils and sudo, plus its systemd units.

## Boot prerequisites

Use the matching new hardware kernel, root initrd, DTB, complete module tree and
firmware products. Cold boot J71t using the PSCI-capable m1n1 with its `psci=1`
payload variable. Both CPUs must use `enable-method=psci`, with `/psci/method=smc`.
A pre-existing spin-table boot cannot be repaired by a userspace package update.
The kernel's cold-reset guard must exist, and all watchdogs must be inactive.
The systemd manager drop-in sets Runtime/Reboot/KExecWatchdogSec to zero.

J71t BLS install entries select
`pcie_apple_h9p.ans_keep_power=1 pcie_apple_h9p.ans_boot_mode=handoff panic=0 apple_wdt.cold_restart=0`.
The release kernel's AOP/ANS/G5P/ADBE and warm PMGR path must be on the **outgoing**
side too. Loading a fixed incoming kernel cannot repair its predecessor.

## Pristine DT provenance

Orchard's platform layer puts each board's pristine DT in the matching initrd.
Before switch_root, the initrd copies the cold board's tree to
`/run/orchard-kexec/pristine.dtb`. A warm boot instead copies the effective pristine
DT from its `orchard_warm.dtb=/var/tmp/orchard-warm.*/pristine.dtb` stage. The initrd
records this boot ID and moves the tmpfs `/run` into the real root.
`orchard-kexec-provenance.service` archives the snapshot under
`/var/lib/orchard-kexec/boots/BOOT-ID/pristine.dtb`. Updates cannot alter it by
replacing `/boot` or reusing a kernel release string. The loader checks the boot
ID and uses this snapshot for `new + (running - old)`. It never substitutes a
pristine target for the running tree. Conflicts, missing provenance, initrd,
unsafe BLS paths, missing PSCI or active watchdogs refuse the load.

Retain each warm stage until it has booted and the next initrd has copied its
pristine DT. Large stages use `/var/tmp` on NVMe. The loader removes the unpacked
Image/initrd/merged DT after the kernel has copied the segments. No firmware
storage, NVRAM or syscfg write is involved.

## Commands and systemd

```sh
sudo orchard-kexec load default       # resolve loader.conf/default and BLS order
sudo orchard-kexec load ENTRY         # explicitly select one BLS entry for the next hop
sudo orchard-kexec reboot             # prepare current default, then systemctl kexec
sudo orchard-kexec status
systemctl reboot                     # the same warm restart policy
systemctl poweroff                   # ordinary poweroff
sudo orchard-kexec ios               # explicit hardware-reset escape hatch
```

The boot load unit prepares the default before login. On Restart,
`orchard-kexec-refresh.service` is NOT part of the reboot/kexec transaction (needing /boot
there conflicts with umount.target); the image is kept current at boot, after updates and by
Restart's preflight. Previously it was required by reboot.target and kexec.target,
and runs before shutdown.target/umount.target: it rereads the latest default and
all linux/initrd/devicetree/options while `/boot` is still mounted. A named load
or the developer wrapper explicitly arms its selection for the next hop.
The final systemd-reboot and systemd-kexec dispatchers use only that boot's
prepared image. If loading fails the restart target fails; no reset is requested.
If preparation was bypassed or an image disappears during shutdown, the final
dispatcher logs a clear refusal and halts. It never falls back to rebooting iOS.
Poweroff has no override. `orchard-kexec ios` is the explicit escape hatch.

The Omarchy menu's **Restart** calls `orchard-restart`, which starts the load unit
while the desktop still exists; failure displays a notification and leaves Linux
running. Successful preflight requests `systemctl reboot`. Local active wheel
sessions may start only this load unit through the included polkit rule.

Enable these when adopting the module into another image:

```sh
systemctl enable orchard-kexec-provenance.service orchard-kexec-load.service \
  orchard-kexec-health.service
```

Both the base-root builder and published-root assembler install/enable them.
The prebuilt base root must be regenerated with `system/packages.txt` so it
contains kexec-tools; copying this overlay onto a base without its dependencies
is insufficient. Hardware's platform initrd must also be regenerated.

## Kernel and firmware updates

Install complete matching kernel/modules/initrd/DTB and firmware assets before
atomically publishing the new BLS entry or loader.conf default. The alpm
`95-orchard-kexec.hook` refreshes the loaded default after boot or module asset
transactions. Image/firmware updaters outside pacman call
`sudo orchard-kexec update` **after** publishing the complete entry. A failed
update refresh unloads the stale image and reports the error. Restart always
refreshes again, so same-path replacements are observed too. Firmware updated
on disk is consumed by the new kernel after the proven outgoing quiesce.

The immutable running pristine DT remains valid even if the old BLS entry and
old boot files are replaced. No Mac-side pristine lookup is needed.

## Health and evidence

`orchard-kexec-health.service` runs the lab quick storage gate, then a late
window with uptime >=120 s and >=60 s of clean observations. It performs bounded
16 KiB O_DIRECT reads, checks completion IRQ progress and rejects timeout or
polled-completion recovery lines from the current boot. A healthy SSH connection
alone is insufficient. This service reports failure; it does not reset the device.

```sh
systemctl status orchard-kexec-health.service
journalctl -b -u orchard-kexec-health.service -u orchard-kexec-load.service
```

The Mac developer wrapper calls the same staged module with diagnostic profiles
and explicit matching-module replacement. Its default netconsole capture is
optional (`--no-netconsole`); on-device Restart requires no Mac, netconsole or
network. A host capture can stop at USB shutdown, and DFU can erase ramoops.
