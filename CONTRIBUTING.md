# Device bring-up

Bring an unknown device, reuse the closest port, attempt a RAM boot, and contribute what you learn. A boot log or partial port is enough for a PR. A desktop and installer can wait.

## 1. Set up

```sh
git clone https://github.com/OrchardLinux/omarchy-a
cd omarchy-a
./orchard --version
```

Requires uv. See [BUILD.md](BUILD.md) for compiler/container dependencies. `cli/` and `hardware/` are editable submodules; no package release or venv activation is needed.

Charge the device and build artifacts before entering DFU.

## 2. Find a starting point

Connect the device in DFU and inspect it:

```sh
./orchard devices
```

Record the `chip` and `board` fields. Discovery lists unknown devices too. The USB `product` name may just say DFU, not the model.

Get the model from Settings → General → About or the case's model number. For the Apple product identifier, such as `iPad7,5`, run `ideviceinfo -k ProductType` with iOS running and the computer trusted. That optional tool comes from libimobiledevice. Missing a model name is not a reason to stop experimenting.

- Find an existing kernel/DTB for that board or the closest SoC. Keep its source revision, patches and licenses.
- Keep any working boot tools and payloads. Change one thing per attempt.
- Do not copy another board's GPIO, regulator or charging writes blindly.

## 3. Build and attempt a RAM boot

```sh
./orchard build examples/minimal-boot
./orchard run examples/minimal-boot
# Without a prompt:
./orchard run examples/minimal-boot --yes
```

The reference kernel/DTB is a starting experiment, not a guarantee it fits your board.

An experiment contains `init` and optional `rootfs/`. Put your startup and diagnostics there. No installer or device-side RPC is needed.

Reuse compiled components. Changing `init` should not rebuild Linux. Keep `hardware/kernel/.work/` and check existing outputs before starting another full compile.

## 4. Add your board's recipe

Work in the `hardware/` submodule:

| Path | Add |
| --- | --- |
| `devices/BOARD/device.toml` | Model name, product identifiers, chip/board IDs and compatible strings. |
| `kernel/configs/BOARD/config` | Kernel configuration. |
| `kernel/devicetree/BOARD/build` | Commands producing the final DTB. Accepts `--kernel-build`, `--headers`, `--output`. |
| `kernel/patches/BOARD/` | Kernel patches, if needed. |
| `kernel/modules/BOARD/` | External modules, if needed. |
| `boot/m1n1/patches/BOARD/` | Applicable loader patches when using the m1n1 producer. |

Use J71b's files as format examples, not hardware settings to copy wholesale. See the [component API](https://github.com/OrchardLinux/cli/blob/main/docs/ram-development.md) to build a named recipe or assemble explicit kernel/DTB/loader inputs.

## 5. Find where it stops

| Observation | Check next |
| --- | --- |
| Still in DFU | Boot-chain tool output and USB transport. |
| Pongo runs, no kernel output | Payload, loader, DTB and console routing. |
| Kernel hangs or panics | Last messages, config, DTB and failing driver. |
| Kernel runs, no init | Initramfs, executable `/init` and boot arguments. |
| Init runs, no USB shell | Controller driver, gadget setup and host serial endpoint. |

Save commands, revisions and logs for each attempt. Successful upload does not prove Linux booted. Missing USB serial does not prove it failed. Inspect an uncertain result before retrying.

## 6. Send the PR

Include:

- Exact device tested and how to reproduce the build/boot.
- Source revisions, patch attribution and relevant logs.
- Furthest boot stage; working, broken and untested hardware.
- Any shared changes that could affect existing ports.

Keep firmware bytes, calibration, raw ADT captures, ECIDs and credentials out of public commits/logs. Contribute firmware recipes instead.

Commit hardware work in `hardware/`, generic host tooling in `cli/`, and distro changes here. Commit shared changes once and update submodule pins. Local Git fetches work before pushing; push referenced commits before publishing parent commits.

Run tests for changed repositories. Check new hardware resources are included in the wheel. Report physical boot results separately from compilation/test results.
