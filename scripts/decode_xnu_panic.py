#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode XNU 12377's packed version-8 embedded panic header."""
import json
from pathlib import Path
import re
import struct
import zlib


def decode(data: bytes, expected_uuid: str) -> tuple[bytes, bytes, dict]:
    if len(data) != 524288:
        raise ValueError('expected the loader-owned 512 KiB panic region')
    magic, crc, version, flags, *spans = struct.unpack_from('<IIIQ6I', data)
    if magic == 0:
        return b'', b'', dict(initialized=False, reason='no finalized panic header')
    if magic != 0x46554e4b or version != 8:
        raise ValueError('unknown embedded panic magic or header version')
    regions = {}
    for index, name in enumerate(('panic', 'stackshot', 'other')):
        start, size = spans[index * 2:index * 2 + 2]
        if size and (start < 225 or start + size > len(data)):
            raise ValueError(f'{name} extent exceeds the captured panic region')
        regions[name] = dict(offset=start, bytes=size)
    nonempty = sorted((v['offset'], v['offset'] + v['bytes']) for v in regions.values() if v['bytes'])
    if any(a[1] > b[0] for a, b in zip(nonempty, nonempty[1:])):
        raise ValueError('overlapping panic and stackshot extents')

    def contents(name):
        value = regions[name]
        return data[value['offset']:value['offset'] + value['bytes']]

    text = contents('panic') + contents('other')
    identity = re.search(rb'Kernel UUID: ([0-9A-Fa-f-]{36})', text)
    if identity and identity[1].decode().upper() != expected_uuid.upper():
        raise ValueError('panic text UUID differs from the matched kernel')
    crc_ok = zlib.crc32(data[8:]) == crc
    report = dict(initialized=True, header_version=version, flags=hex(flags),
                  crc_matches=crc_ok, uuid_verified=bool(identity), kernel_uuid=expected_uuid,
                  sections=regions, stackshot_compressed=bool(flags & 0x800),
                  complete=crc_ok and bool(identity) and not bool(flags & 0x8000),
                  hardware_transport_qualified=False, warm_reboot_retention_qualified=False)
    return text, contents('stackshot'), report


def save(directory: Path, data: bytes, kernel_uuid: str) -> dict:
    # Keep the raw region even when an interrupted panic cannot be decoded.
    (directory / 'xnu-panic.bin').write_bytes(data)
    try:
        text, stackshot, report = decode(data, kernel_uuid)
    except ValueError as error:
        text, stackshot, report = b'', b'', dict(decoded=False, error=str(error))
    (directory / 'xnu-panic.txt').write_bytes(text)
    (directory / 'xnu-stackshot.bin').write_bytes(stackshot)
    (directory / 'xnu-panic.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
