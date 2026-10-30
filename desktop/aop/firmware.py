#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only OR MIT
"""Validate the locally extracted AOP container and launch with RAM-only images."""
import hashlib
import os
from pathlib import Path
import struct

CONTAINER_SHA256 = "8746c6b80c0b1553d2a59b545a6135e00f6c8a0e750ef93f0ebf381eaccb4be6"
IMAGES = (
    ("AOP", 0x86d60, "b9db3a9601b357d469ed79c2fa6b26c8e5fb4a3953ce289687f4ab434da338f1"),
    ("AOP_ext", 0xa2a0, "25367930b9015e5c20d20a56d959a5e3e5fa713bc3b97aeef604c0ede9e74fc1"),
)


def unserialize(data):
    """Bounded OSSerializeBinary reader for the pinned AOP image container."""
    position, objects = 4, []
    if data[:4] != b"\xd3\0\0\0" or len(data) > 1024 * 1024:
        raise ValueError("invalid AOP container")

    def take(size):
        nonlocal position
        if size < 0 or size > len(data) - position:
            raise ValueError("truncated AOP container")
        result = data[position:position + size]
        position += size
        return result

    def read(depth=0):
        if depth > 16 or len(objects) > 1024:
            raise ValueError("AOP container nesting/object limit")
        header, = struct.unpack("<I", take(4))
        kind, size = (header >> 24) & 0x7f, header & 0xffffff
        if kind == 12:
            if size >= len(objects):
                raise ValueError("invalid object reference")
            return objects[size]
        if kind in (1, 2):
            if size > 128:
                raise ValueError("AOP collection too large")
            value = {} if kind == 1 else []
            objects.append(value)
            for _ in range(size):
                key = read(depth + 1)
                if kind == 1:
                    if not isinstance(key, str) or key in value:
                        raise ValueError("invalid AOP dictionary key")
                    value[key] = read(depth + 1)
                else:
                    value.append(key)
            return value
        if kind in (8, 9, 10):
            value = take(size)
            take((-size) % 4)
            if kind != 10:
                value = value.rstrip(b"\0").decode("utf-8")
        elif kind == 4 and size == 64:
            value, = struct.unpack("<Q", take(8))
        elif kind == 11 and size in (0, 1):
            value = bool(size)
        else:
            raise ValueError("unsupported AOP container object")
        objects.append(value)
        return value

    value = read()
    if position != len(data):
        raise ValueError("trailing AOP container data")
    return value


def images(data):
    if hashlib.sha256(data).hexdigest() != CONTAINER_SHA256:
        raise ValueError("AOP firmware hash differs from the J71b recipe")
    document = unserialize(data)
    entries = document["firmware"]
    if len(entries) != len(IMAGES):
        raise ValueError("unexpected AOP image count")
    result = []
    for entry, (role, size, digest) in zip(entries, IMAGES):
        image = entry["data"]
        if (entry["header"]["coprocessor"] != role or len(image) != size or
                hashlib.sha256(image).hexdigest() != digest):
            raise ValueError("unexpected AOP image")
        result.append(image)
    return result


def main():
    # Orchard extracts this at installation from its cached IPSW. No embedded
    # firmware, modified images on disk, or per-device environment file.
    data = Path("/usr/lib/firmware/apple/j71b-aop.osbin").read_bytes()
    descriptors = []
    try:
        for image in images(data):
            fd = os.memfd_create("apple-aop-image", 0)
            descriptors.append(fd)
            with os.fdopen(os.dup(fd), "wb") as stream:
                stream.write(image)
            os.lseek(fd, 0, os.SEEK_SET)
        os.execv("/usr/libexec/apple-aop-daemon", ["apple-aop-daemon",
                 *(f"/proc/self/fd/{fd}" for fd in descriptors),
                 "/run/apple-aop/orientation"])
    finally:
        for fd in descriptors:
            os.close(fd)


if __name__ == "__main__":
    main()
