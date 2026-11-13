# Warm restart

The menu stays **Restart** on every device. Warm restart is used where the
system has what it needs, and `orchard-kexec supported` answers that from the
mechanisms themselves: the running kernel's kexec support
(`/sys/kernel/kexec_loaded`), kexec-tools, and the kernel's tethered reset guard
described below. There is no board list and no feature-state lookup. Today only
J71t's kernel describes the tethered boot on its watchdog, so only J71t warm
restarts; other boards (including J71b) use normal reboot, silently.

Where those exist, Restart and `orchard-restart` load the selected BLS default
before systemd kexec. The matching initrd retains the running pristine DT and
boot ID. Canonically equal pristine trees use the file loader; changed trees
merge runtime fixups with the legacy loader. No silent fallback after failure.
The plan records `pristine_dt_changed` for the integration checker.

Require `/sys/kernel/reboot/mode` plus `apple,tethered-boot` on an enabled
`apple,wdt` node, or the older `apple_wdt` `cold_restart` parameter. Reboot sysfs
alone is insufficient. Loading validates; dispatch selects warm (old: N).
Incoming guarded trees use reboot=warm; old targets also get the old parameter.
Health, status and diagnostics report the same contract. CPU lifecycle/kexec
requires the resident PSCI loader with `psci=1 psci_reset=0`.

The final kexec hook requires GPU quiesce success before dispatch. Missing image
halts safely. Reboot (leaves Linux) retains its ordinary action: a separate reboot
hook selects cold (old: Y) and leaves systemd's shutdown command intact.
`orchard-kexec ios` explicitly exits too. Unguarded kernels still reboot normally
but cannot warm restart. Poweroff is unchanged.

Public-root assembly enables provenance/load/health units; incremental overlays
must enable those after installing files. The pacman hook refreshes images after
updates. Refresh is never part of shutdown because it needs mounted /boot.
Host tests do not qualify hardware; J71t and J71b device tests remain required.
