# N61 development NFS host

This container serves a private root produced by `release.n61.prepare_nfs`.
Its source must live on a Linux filesystem that preserves numeric ownership
and package modes. Use a dedicated container and bind its published TCP port
to the NFS host's loopback address. The N61 USB host forwards port 32061 onto
the phone's dedicated link at 10.61.0.1.

`n61.conf` selects NFSv4 over TCP and sends numeric UID/GID attributes so the
RAM client can preserve guest ownership without a name-mapping daemon. It is
intended for the trusted USB development link. Keep the root and its keys
private. The VFS backend requires a container with permission to open Linux
filesystem handles; a rootless container cannot supply that host capability.

Build with the project's separate N61 Podman endpoint selected:

```sh
podman build -f tools/nfs/Containerfile -t localhost/orchard-n61-nfs:bookworm tools/nfs
```

Bind the prepared root at `/srv/root` and this configuration read-only at
`/etc/ganesha/ganesha.conf`. Publish `127.0.0.1:32061:2049/tcp`. Record the
container image ID, root identity and owned forwarding process with the boot
evidence. Host exports and containers used by other devices stay in place.

Supply `--tmpfs /run:rw,nosuid,nodev,mode=0755` when creating the container.
Its RPC and D-Bus processes keep PID files there; a fresh runtime directory
allows the same container to restart after its processes have exited.

The hardware runtime owns root validation and PID 1 handoff. This server
supplies the file service and has no device boot or storage operation.
