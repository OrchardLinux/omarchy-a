# Supported devices and features

Omarchy A is experimental on every device. Boot is tethered and there is no GPU acceleration. "Works" means verified on hardware, "Partial" means it works with limits or only parts are verified, and "Not yet" means not available.

| Device | Identifier | Chip / board | Tested |
| --- | --- | --- | --- |
| iPad 6 Wi-Fi | `iPad7,5` / J71b | T8010 (A10), board `0x18` | See the J71b column note |
| iPad 5 Wi-Fi | `iPad6,11` / J71t | S8003 (A9, TSMC), board `0x10` | One unit, iPadOS 16.7.10 |

`iPad6,11` is also sold as J71s (Samsung S8000, chip `0x8000`). J71s and the cellular iPad 5 (`iPad6,12`, J72s/J72t) are not supported.

## Features

| Feature | J71b¹ | J71t² |
| --- | --- | --- |
| Wi-Fi | Supported (a) | **Works**: BCM4355 C0 over PCIe; MAC and calibration come from the iPad's own device tree; 5 GHz verified |
| Bluetooth | Supported (a) | **Works**: scan and keyboard pairing |
| Touch | Supported (a) | **Works**: N1 multitouch; firmware from the IPSW, per-unit calibration from the device tree |
| Display | Supported, no GPU acceleration (b) | **Works**: native KMS at 1536×2048 on the display pipe iBoot leaves running; the panel is `eDP-1`. Software rendering only. Booting with `apple_adbe_drm.enable=0` falls back to the boot framebuffer (simpledrm) |
| Brightness / ambient light | Backlight supported (c); ALS — | **Works** for brightness: the brightness slider and power-key screen toggle. The CT819 light sensor is exposed through IIO only, with no automatic brightness |
| Audio out | — | **Works**: speakers (CS42L81) through PipeWire's default ALSA profile. Headphone jack: routing code present, not validated |
| Microphones | — | **Works**: built-in stereo microphones (48 kHz capture verified) |
| Battery | Supported (d) | **Works**: bq27540 gauge, read-only telemetry; the status reads Discharging whenever current flows out, also at 100 % |
| Charging (detection, up to 2.4 A) | Partial: guarded 425 mA lease (e) | **Works**: computers (USB-A, and a Mac USB-C port through Apple's USB-C to Lightning cable), USB-C wall chargers and a Mac USB-C power adapter charge at up to 2.4 A, the board maximum (verified on the device on 2026-10-27). 5 V only: the iPad 5 has no USB Power Delivery. Charging policy runs in the kernel |
| NVMe install | Supported (f) | **Partial**: untested through Orchard. Installing to a Linux partition beside a shrunk iOS works with the omarchy-ipad5 port's own installer and kernel write fence |
| Suspend | Disabled by image policy (g) | **Not yet**: disabled by image policy, as on J71b; s2idle is only partially validated |
| USB gadget | Supported (h) | **Works**: USB networking and serial console to the host |
| Lightning camera adapter | — | **Partial**: switches to host mode, but no hub or device enumerates yet and host-mode input is limited to 100 mA |
| Accelerometer / auto-rotate | — | **Not yet** in this port: the AOP driver can only be built in, needs a boot-time release step from the omarchy-ipad5 port's own initramfs, and Orchard cannot yet generate its calibration from the device tree. Works on cold boot in omarchy-ipad5 |
| GPU | Not supported (b) | **Not yet**: software rendering only; GPU research code is excluded from this port |
| Video decode | — | **Partial**: V4L2 stateless H.264 decoder, bit-exact on a test stream. Its firmware comes from the IPSW and starts only on request, through debugfs; no media player is set up to use it |
| Cameras | — | **Not yet**: no driver |

Also not in the J71t port: Touch ID / Secure Enclave (communication only, no fingerprint support), deeper CPU idle and overclocking profiles, and the shared cold-restart launcher (`orchard launch`), which needs J71t launcher assets first. Resize APFS support for iPad 5 has not been checked.

¹ J71b entries state only what Orchard's own code and documentation show; "—" means not stated there (maintainer to confirm). Sources: (a) hardware `runtime/j71b/phase2-hardware` (Wi-Fi, touch and Bluetooth steps) and `devices/j71b/device.toml`; (b) [README](../README.md); (c) `system/j71b/overlay/usr/lib/udev/rules.d/70-j71b-backlight.rules` and the power-key screen toggle; (d) hardware `kernel/devicetree/j71b/battery-gauge.dtso` and `system/j71b/overlay/usr/lib/modprobe.d/30-j71b-battery.conf`; (e) `system/j71b/overlay/usr/lib/systemd/system/j71b-charge.service`; (f) [How it works](how-it-works.md); (g) `system/j71b/overlay/etc/systemd/sleep.conf.d/60-omarchy-a-no-suspend.conf`; (h) hardware `boot/initramfs/j71b/recovery/usb-gadget` and `omarchy-diagnostics.service`.

² J71t statuses come from device tests of the same drivers in the release 2 kernel of the [omarchy-ipad5](https://github.com/brkosebay/omarchy-ipad5) port, which passed 13 of 13 device checks through that port's own boot path on one iPad6,11 J71t (S8003, board `0x10`) running iPadOS 16.7.10. Kernel source: [`a9/orchard-j71t`](https://github.com/brkosebay/linux/tree/a9/orchard-j71t). Charging was verified on the same unit on 2026-10-27 with the charger code of kernel patch 0013. The Orchard recovery, installation and handoff path has not yet run on a J71t.
