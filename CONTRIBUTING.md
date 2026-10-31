# Contributing

This repository holds the Omarchy A desktop, its root filesystem and its release.
Hardware support, kernel and driver work, firmware recipes and the `orchard` tool
belong in [orchard](https://github.com/OrchardLinux/orchard); bringing up a new
device follows its
[bring-up guide](https://github.com/OrchardLinux/orchard/blob/main/docs/device-bring-up.md)
and needs no distribution.

## Set up

```sh
git clone https://github.com/OrchardLinux/omarchy-a
cd omarchy-a
orchard --version
```

Put orchard's launcher on your PATH first (see its README). `orchard` runs orchard's
`main` here; `orchard.local.toml` (never committed) can name your own orchard
checkout and your board. See [BUILD.md](BUILD.md) for compiler and container
dependencies.

## Work that spans both

If a desktop change needs an orchard change, make it on an orchard branch, point
`orchard.local.toml` at that checkout, and open one PR in each repository. Say in
each which one it needs and in which order they merge.

Pull requests land as in orchard: we usually rework them to fit the structure
before merging, on your PR branch and with your authorship, unless you ask us
not to (see orchard's [CONTRIBUTING](https://github.com/OrchardLinux/orchard/blob/main/CONTRIBUTING.md#how-pull-requests-land)).

## Test

```sh
orchard python -m unittest discover -s tests
```

Report physical boot and desktop results separately from compilation and test
results. Keep firmware bytes, calibration, raw ADT captures, ECIDs and credentials
out of public commits and logs.
