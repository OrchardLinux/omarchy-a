# Troubleshooting

## Apple logo stuck during bootstrap

Follow the CLI's cable-reconnect instruction: briefly disconnect the cable at the device, then reconnect it.

## Recovery is visible, but SSH cannot connect

Enable DHCP on the host's USB Ethernet interface. The current port uses `172.16.42.2` for the host and `172.16.42.1` for the device.

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
