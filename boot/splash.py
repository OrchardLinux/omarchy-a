#!/usr/bin/env python3
"""orchard's boot splash (docs/boot-contract.md) from the m1n1 artwork header.

The same mask, size and colour as m1n1/patches/0002-omarchy-splash.patch
draws, so install (our m1n1) and orchard launch (the boot entry's splash)
look alike: drawn 1:1, centred on black.
"""
import argparse
from pathlib import Path
import re
import struct

GREEN, BLACK = (0x9e, 0xce, 0x6a), (0, 0, 0)


def splash(header):
    size = int(re.search(r'#define OMARCHY_LOGO_SIZE (\d+)u', header).group(1))
    body = re.search(r'omarchy_logo_mask\[\] = \{(.*?)\};', header, re.S).group(1)
    mask = bytes(int(value, 16) for value in re.findall(r'0x([0-9a-f]{2})', body))
    pixels = bytearray()
    for bit in range(size * size):
        r, g, b = GREEN if mask[bit // 8] & (0x80 >> (bit % 8)) else BLACK
        pixels += bytes((b, g, r, 0))  # the framebuffer's XRGB8888
    return struct.pack('<4sII', b'OSPL', size, size) + pixels


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('header', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_bytes(splash(args.header.read_text()))


if __name__ == '__main__':
    main()
