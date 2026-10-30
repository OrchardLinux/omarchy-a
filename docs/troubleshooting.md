# Troubleshooting

## Apple logo stuck during bootstrap

Follow the CLI's cable-reconnect instruction: briefly disconnect the cable at the device, then reconnect it.

Do it within about 20 seconds of the logo appearing. After that, palera1n gives up (`Timed out waiting for download mode` in the palera1n log under `~/.local/share/orchard/private/devices/`), and the device needs a fresh DFU entry.

## `Expected dfu at the selected port; found pongo`

Something other than this Orchard command already exploited the device, usually a palera1n or checkra1n process left over from an earlier attempt. Stop it (`pkill -f checkra1n; pkill palera1n`), force-restart the iPad and enter DFU again. Orchard releases newer than cli 0.1.10 stop the leftover process themselves.

## `No free space or Linux partition of at least 9 GiB`

The installer needs free space next to iPadOS, or an earlier Linux install to replace; it never resizes iPadOS. Repeat [Make room for Linux](../README.md#3-make-room-for-linux) and reserve more space.

## Recovery is visible, but SSH cannot connect

Enable DHCP on the host's USB Ethernet interface. The current port uses `172.16.42.2` for the host and `172.16.42.1` for the device.

If every SSH request fails with `Invalid device response`, check what `ssh` resolves to (`type -a ssh`). Orchard reads device replies from `ssh`'s standard output, so a wrapper script or alias that prints anything breaks the protocol. Put the real `ssh` first in `PATH` while running Orchard.

## The host loses its internet connection during recovery

Recovery images up to hardware 0.1.10 advertise `172.16.42.1` as a default gateway. NetworkManager's automatic wired profile accepts it with a lower metric than Wi-Fi, so traffic goes to the iPad, which doesn't forward it. Give the USB link a profile that never becomes the default route:

```sh
nmcli connection add type ethernet con-name orchard-usb ifname '*' match.driver cdc_ncm \
  connection.autoconnect-priority 300 ipv4.method auto ipv4.never-default yes \
  ipv4.ignore-auto-routes yes ipv4.ignore-auto-dns yes ipv6.method link-local ipv6.never-default yes
```

## Inspect the running system

While diagnostic SSH remains available for this boot:

```sh
orchard status
orchard diagnostics
```

These commands require the credentials established for the current device and boot. See the [orchard documentation](https://github.com/OrchardLinux/orchard#develop) for detailed workflows.

## Installation failed or stopped responding

Run `orchard install` again. It reads the disk afresh, and a partition an interrupted run created shows up as a target to replace. The install log is `/run/orchard/install.log` on the recovery until it restarts.

- The installer checks the partition table against its plan before the first write and refuses a stale plan; nothing is changed then.
- Replacing an existing installation permanently deletes it without a backup.
- If Omarchy A doesn't start after the install, put the iPad in DFU mode and run `orchard launch`.

See [How it works](how-it-works.md) for the installation lifecycle and failure handling.
