# Publishing Omarchy A

Build and validate a coherent local release using [BUILD.md](../BUILD.md). Its rootfs and recovery must be produced together; do not combine artifacts from different builds.

## GitHub builds

Push a `v*` version tag to run the native build workflow and create a draft release, or use manual dispatch to build downloadable workflow artifacts without creating a release. Its component release tag must already be published; the tools are orchard's `main`, and the receipt records the exact commit. See [BUILD.md](../BUILD.md#github-actions). Review and qualify the draft before publishing; the automatic-login/passwordless-sudo warning remains required.

Public tag/manual builds attest all final assets, including `SHA256SUMS`, and retain `omarchy-a-build.sigstore.jsonl` with workflow/draft release assets. Private or unknown-visibility builds skip signing and bundle copying. Signing permissions belong only to final assembly; public signing failures prevent release creation. The bundle is not listed in the signed checksum manifest. Verify a file with `gh attestation verify FILE --repo OrchardLinux/omarchy-a`; this does not qualify the image on a device.

## Prepare hosted assets

From `omarchy-a/`:

```sh
python3 -m release.publish \
  --release-dir out/releases/0.1.0-orchard.3 \
  --tag v0.1.0-orchard.3 \
  --output out/publication/v0.1.0-orchard.3
```

Use the intended immutable GitHub release tag. The tool:

1. Verifies the local index, manifests, and artifact receipts.
2. Rewrites manifest artifact references as versioned GitHub HTTPS URLs.
3. Recomputes each manifest's size/hash in the hosted index.
4. Stages the images and metadata in a new output directory, leaving local metadata unchanged.

Image files are hardlinked when possible, copied otherwise. Treat the staged files and original release as immutable. This prepares assets; it neither uploads nor qualifies a build on hardware.

## Publish

Upload all files from the publication directory to the matching `OrchardLinux/omarchy-a` GitHub release. Mark the release as latest so this stable entry point works:

```text
https://github.com/OrchardLinux/omarchy-a/releases/latest/download/index.toml
```

Only that entry point follows latest. Its manifest and image references point to specific release tags, preventing cross-release mixing.

Every release carries its installer: `install.sh` and `orchard-install.pyz` (orchard's core with this release's index, device data and launch loaders), made by `orchard.installer` from the orchard release CI pins and rewritten by `release.publish` for the release's URLs. The README's command runs the latest release's `install.sh`; the repository's `install.sh` only forwards to it, for older instructions. Publish the pinned [orchard release](https://github.com/OrchardLinux/orchard/blob/main/docs/releases.md) first: its tag provides the components and the loaders. Change the README's install command only once a release with `install.sh` is published.

Before announcing a release:

- Resolve its hosted index with `orchard resolve https://github.com/OrchardLinux/omarchy-a/releases/latest/download/index.toml` from a clean host environment.
- Test installation and `orchard launch` after a cold restart on supported hardware; do not infer device qualification from unit tests or container checks.
- Confirm the published root and recovery come from the audited build and retain their build receipts, source pins, licenses and corresponding source/build inputs.
- Include the experimental status and the README's automatic-login/passwordless-sudo warning in release notes.

## Updates

The installer leaves the user's `orchard` (`install`, `launch`, `devices`, `update`); a later installer replaces it only with a newer core, and `orchard update` installs the latest orchard release's core.

Running the README command again installs the latest release. Cached images are verified and reused by hash. This updates available installation data; upgrading an existing desktop installation is a separate, currently unimplemented workflow.
