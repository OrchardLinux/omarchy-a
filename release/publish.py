#!/usr/bin/env python3
"""Stage Omarchy A assets with the shared, integrity-checked publisher."""
import argparse
from pathlib import Path
from orchard_hardware.image.publish import publish as publish_distro


def publish(directory, tag, output):
    return publish_distro(directory, tag, output, distro="omarchy-a")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(publish(args.release_dir, args.tag, args.output))


if __name__ == "__main__":
    main()
