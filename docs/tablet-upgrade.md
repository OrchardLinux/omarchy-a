# Standalone tablet upgrade

Stage an overlay from this checkout and a matching wlroots0.20 package:

```sh
python -m release.tablet_overlay /var/tmp/tablet-upgrade --wlroots-package /path/to/wlroots0.20.pkg.tar.xz
python /var/tmp/tablet-upgrade/apply.py
sudo python /var/tmp/tablet-upgrade/apply.py --apply
```

The default prints a plan. Apply verifies archive hashes, paths and file
metadata before writing, and backs up replaced files and package state.
Use `--root DIR` for an offline root without package or service operations.
Log out and back in after applying; reboot separately for memory policy.
The caller must supply a package built for the installed architecture.
No kernel, firmware or Mesa package is installed by this command.

The installer adds iio-sensor-proxy, udiskie and udisks2 with the matching
wlroots package. It does not add alsa-utils or change headphone routing.
Warm restart is installed as a complete unit/helper/polkit set only when
it can run: kexec-tools in the target root, and kexec support plus the
tethered reset guard in the running kernel (what `orchard-kexec supported`
checks); otherwise Restart uses ordinary reboot. Boot-time restart units are enabled for the next boot.
