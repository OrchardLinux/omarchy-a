# Contributing

Read [How Omarchy A gets from DFU to desktop](docs/how-it-works.md) for the release components, host/device boundary, and installation lifecycle. See [BUILD.md](BUILD.md) for image assembly and validation.

## Bringing up a device

A new device needs working hardware support and a host adapter. A manifest entry describes the resulting release; it does not supply that implementation.

The current J71b port is the reference implementation:

- [Hardware support](https://github.com/OrchardLinux/hardware): kernel patches, device trees, firmware recipes, device runtime, and early-boot support.
- [Host adapter contract](https://github.com/OrchardLinux/cli/blob/main/docs/adapter-contract.md): discovery, boot transport, authenticated connection, device-tree capture, and firmware preparation.
- [Device protocol](https://github.com/OrchardLinux/cli/blob/main/docs/device-protocol.md): operations exposed by the runtime to the host.
- Omarchy A's `image/j71b/` and `release/j71b/`: installed-system policy and release assembly.

Keep device-specific hardware procedures in the hardware implementation and desktop policy in Omarchy A. The host coordinates operations and presents confirmations; the device runtime owns storage validation, hardware activation, extraction, and handoff.
