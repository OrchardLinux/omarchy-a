# Contributing

This repository holds the Omarchy A desktop, its root filesystem and its release.
Hardware support, kernel and driver work, firmware recipes and the `orchard` tool
belong in [orchard](https://github.com/OrchardLinux/orchard); bringing up a new
device follows its
[bring-up guide](https://github.com/OrchardLinux/orchard/blob/main/docs/device-bring-up.md)
and needs no distribution.

## Everything benefits every device

**Every change benefits every device it can.** A desktop, audio, power or
input change applies to every board that has the hardware, not only the one
you tested on. Key it on what the device has (a driver, a sensor, a property
it reports), not on a board name.

**Every opt-in or opt-out needs a very good reason, written next to it:** the
hardware is absent, or there is evidence that it breaks that board.
**"Untested" is never a reason.**

## Set up

```sh
git clone https://github.com/OrchardLinux/omarchy-a
cd omarchy-a
orchard --version
```

Put orchard's launcher on your PATH first (see its README). `orchard` runs orchard's
newest nightly here; your own orchard checkout runs with its `bin/orchard`, and
`orchard.local.toml` (never committed) can name your board. See [BUILD.md](BUILD.md) for compiler and container
dependencies.

## Work that spans both

If a desktop change needs an orchard change, make it on an orchard branch, build
with that checkout's `bin/orchard`, and open one PR in each repository. Say in
each which one it needs and in which order they merge.

Pull requests land as in orchard: we usually rework them to fit the structure
before merging, on your PR branch and with your authorship, unless you ask us
not to (see orchard's [CONTRIBUTING](https://github.com/OrchardLinux/orchard/blob/main/CONTRIBUTING.md#how-pull-requests-land)).
Read the merge comment carefully: merges are often partial, and the comment
says what changed on your branch, what was left out and which follow-up work
is open.

If someone using the tablet would notice the change, add a line under
Unreleased in [CHANGELOG.md](CHANGELOG.md). It becomes the release notes. If
you don't, we add it when the PR lands.

## Test

```sh
orchard python -m unittest discover -s tests
```

Report physical boot and desktop results separately from compilation and test
results. Keep firmware bytes, calibration, raw ADT captures, ECIDs and credentials
out of public commits and logs.
