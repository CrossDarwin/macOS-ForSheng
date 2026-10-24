#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Publish the native EL1 text-protection state in generated Apple DTs."""
from pathlib import Path
import struct


def configure_native_text_state(path: Path) -> None:
    data = path.read_bytes()
    chosen = 0

    def node(at: int, parents: tuple[str, ...] = ()) -> tuple[bytes, int]:
        nonlocal chosen
        if len(parents) > 32 or at + 8 > len(data):
            raise ValueError('invalid generated device-tree node')
        count, children = struct.unpack_from('<II', data, at)
        at += 8
        if count > 4096 or children > 4096:
            raise ValueError('excessive generated device-tree counts')
        properties = {}
        encoded = bytearray()
        for _ in range(count):
            start = at
            if at + 36 > len(data):
                raise ValueError('truncated device-tree property')
            key, size = struct.unpack_from('<32sI', data, at)
            key = key.split(b'\0', 1)[0].decode('ascii')
            at += 36
            end = at + ((size + 3) & ~3)
            if end > len(data) or key in properties:
                raise ValueError('invalid or repeated device-tree property')
            properties[key] = data[at:at + size]
            encoded.extend(data[start:end])
            at = end
        name = properties.get('name', b'').rstrip(b'\0').decode('ascii')
        location = (*parents, name)
        if location == ('device-tree', 'chosen'):
            chosen += 1
            key = 'kernel-ctrr-to-be-enabled'
            value = struct.pack('<I', 0)
            if key in properties:
                if properties[key] != value:
                    raise ValueError('native EL1 tree claims unsupported CTRR protection')
            else:
                encoded.extend(struct.pack('<32sI', key.encode(), len(value)) + value)
                count += 1
        result = bytearray(struct.pack('<II', count, children)) + encoded
        for _ in range(children):
            child, at = node(at, location)
            result.extend(child)
        return bytes(result), at

    result, end = node(0)
    if end != len(data) or chosen != 1:
        raise ValueError('requires one complete generated /chosen node')
    path.write_bytes(result)
