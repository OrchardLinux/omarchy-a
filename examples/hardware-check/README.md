# hardware-check

A RAM-only system that checks what a device offers and writes a report you can
send back. It works on every Orchard device: each check looks at what is
present first, and what the device doesn't have is reported as SKIP, not FAIL.
Nothing is written to the device's storage; NVMe is set read-only as soon as it
appears.

## Run it

```sh
./orchard build examples/hardware-check --device <board> --modules --firmware
./orchard run examples/hardware-check
./orchard shell                        # or: screen /dev/cu.usbmodem* 115200
```

At the shell, run `hardware-check`. It takes about three minutes and checks:

- storage (read-only, a 1 GiB read);
- PCIe devices and their drivers;
- Wi-Fi: firmware load, scan, association, DHCP, the gateway, a timed download;
- the battery gauge and other power supplies;
- display and backlight;
- the kernel log (IOMMU faults, NVMe timeouts, warnings, oopses).

Then, if you want: `hardware-check touch`, `hardware-check keys` and
`hardware-check charge` (plug chargers in and out). `hardware-check wifi` runs
only the Wi-Fi checks.

The report is `/run/hardware-check.txt`, the kernel log `/run/dmesg.txt`. With USB
networking up (the host gets 172.16.42.2), both are at `http://172.16.42.1:8080/`.

`--firmware` puts the device's firmware into the image; the first build
downloads the device's IPSW once and caches it. `--modules` includes the kernel
modules, which the image loads for the devices it finds.

## Wi-Fi

For the association test, create `rootfs/etc/wpa_supplicant.conf` (WPA2):

```
network={
	ssid="your network"
	psk="your passphrase"
}
```

For a timed, checksummed download, create `rootfs/etc/hardware-check.conf`:

```sh
DOWNLOAD_URL=http://192.168.0.10:8000/10MB.bin
DOWNLOAD_SHA256=<sha256 of that file>
```

The download runs five times, each stopped after 60 s; a file of about 10 MB
keeps the check short.

Both files stay local: `.gitignore` keeps them out of git. Without them, those
checks are skipped. With `wpa_supplicant.conf` in the image, the Wi-Fi checks
also run by themselves at boot; their report is at the same address when they
finish.
