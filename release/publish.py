#!/usr/bin/env python3
"""Stage Omarchy A assets with orchard's integrity-checked publisher (orchard.image.publish)."""
import argparse
from pathlib import Path
import subprocess

from release import snapshot


def publish(directory, tag, output, orchard=None):
    snapshot.command(snapshot.directory(orchard), 'orchard.image.publish', '--distro', 'omarchy-a', '--tag', tag,
                     '--release-dir', directory, '--output', output, stdout=subprocess.DEVNULL)
    return Path(output) / 'index.toml'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument('--orchard', type=Path, help='the orchard snapshot (default: ORCHARD_CHECKOUT)')
    args = parser.parse_args()
    print(publish(args.release_dir, args.tag, args.output, args.orchard))


if __name__ == "__main__":
    main()
