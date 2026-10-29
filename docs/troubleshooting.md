# Troubleshooting

## Apple logo stuck during bootstrap

Follow the CLI's cable-reconnect instruction: briefly disconnect the cable at the device, then reconnect it.

Do it within about 20 seconds of the logo appearing. After that, palera1n gives up (`Timed out waiting for download mode` in the palera1n log under `~/.local/share/orchard/private/devices/`), and the device needs a fresh DFU entry.

## `Expected dfu at the selected port; found pongo`

Something other than this Orchard command already exploited the device, usually a palera1n or checkra1n process left over from an earlier attempt. Stop it (`pkill -f checkra1n; pkill palera1n`), force-restart the iPad and enter DFU again. Orchard releases newer than cli 0.1.10 stop the leftover process themselves.

## `No available GPT Linux-data partition`

The installer only uses an existing, unformatted GPT Linux-data partition. Repeat [Make room for Linux](../README.md#3-make-room-for-linux) and make sure **unformatted Linux partition** is selected. Adjusting the APFS size alone doesn't create one.

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

These commands require the credentials established for the current device and boot. See the [CLI documentation](https://github.com/OrchardLinux/cli#documentation) for detailed workflows.

## Installation failed or stopped responding

Follow the reported recovery instructions. A failed attempt can require cleanup and a fresh DFU boot.

- Never blindly repeat a format whose outcome is unknown. Inspect the partition and saved report first.
- A readiness timeout can occur after the root filesystem has been installed. Do not reinstall solely because that check timed out; inspect status and diagnostics first.
- Replacing an existing installation permanently deletes the selected destination without a backup. A failed replacement cannot restore those contents.

See [How it works](how-it-works.md) for the installation lifecycle and failure handling.
