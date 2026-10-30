# Branded J71b Pongo

A 600x600 green Omarchy logo on black, with on-device text suppressed while
preserving the existing USB shell/stdout paths.

`upstream.lock` pins Pongo and newlib source revisions. Local and GitHub builds
use `python boot/build-pongo.py --output NEW_PONGO_FILE` from this repository.

The Pongo pin must include upstream `ad8b2d1` ("Fix for Xcode 16.3: don't depend
on section order"). Older pins built with Xcode 16.3 or later copy only part of
the image into SRAM: the copy ends at `__pongo_exports`, which the newer linker no
longer places last. The resulting Pongo never reaches USB on A9. It reboots into
iOS or fails with `softboot e0004051`.

## Native macOS build (no Podman)

Requires Xcode with iPhoneOS SDK, native make/host C compiler, Python 3,
`rsvg-convert` and ImageMagick `magick`. The upstream build fetches/builds its
pinned newlib submodule. Check disk headroom before fetching/building.

From the repository root, for a **new checkout**:

```sh
mkdir -p boot/pongo/.work
git clone --no-checkout https://github.com/checkra1n/PongoOS.git boot/pongo/.work/source
git -C boot/pongo/.work/source checkout --detach ad8b2d158588e929ae1ce7d9fd8d453720e1a8b6
git -C boot/pongo/.work/source submodule update --init --recursive
git -C boot/pongo/.work/source apply "$PWD/boot/pongo/patches/0001-omarchy-splash.patch"
```

Generate the mask and run host renderer tests:

```sh
python3 boot/pongo/generate-logo.py \
  --output boot/pongo/.work/source/src/drivers/framebuffer/omarchy-logo.h
python3 boot/pongo/test-renderer.py
```

Build only Pongo (not the jailbreak KPF):

```sh
make -C boot/pongo/.work/source -j4 PONGO_CFLAGS=-DOMARCHY_SPLASH build/Pongo.bin
mkdir -p out/boot/j71b
cp boot/pongo/.work/source/build/Pongo.bin out/boot/j71b/Pongo-omarchy-600.bin
shasum -a 256 out/boot/j71b/Pongo-omarchy-600.bin
```

Use a clean upstream build directory when switching branded/unbranded compiler
flags: make may not notice a flags-only change. Retain the MIT notices and
other applicable upstream license files when distributing binaries.
