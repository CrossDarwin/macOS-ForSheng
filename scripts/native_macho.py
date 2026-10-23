#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read native ARM64/ARM64E artifacts without relaxing legacy prelink admission."""
from pathlib import Path
import struct


def macho(data: bytes, arch: str | None = None) -> dict:
    if len(data) < 32:
        raise ValueError('truncated native Mach-O header')
    magic, cpu, subtype, kind, count, size = struct.unpack_from('<6I', data)
    actual = {0: 'arm64', 2: 'arm64e'}.get(subtype & 0xff)
    if magic != 0xfeedfacf or cpu != 0x100000c or actual is None or arch and actual != arch:
        raise ValueError(f'native Mach-O architecture mismatch: {actual}, expected {arch}')
    end = 32 + size
    if not 0 < count <= 4096 or end > len(data):
        raise ValueError('native load commands exceed file')
    result = dict(kind=kind, architecture=actual, subtype=subtype, commands=[], segments=[])
    pos = 32
    for _ in range(count):
        if pos + 8 > end:
            raise ValueError('truncated native load command')
        cmd, length = struct.unpack_from('<II', data, pos)
        if length < 8 or length % 8 or pos + length > end:
            raise ValueError('invalid native load command')
        result['commands'].append((cmd, pos, length))
        if cmd == 0x19:
            if length < 72:
                raise ValueError('truncated native segment')
            name, va, span, off, backed, maximum, initial, sections, _ = struct.unpack_from('<16s4Q4I', data, pos + 8)
            if length != 72 + sections * 80 or backed > span or va + span > 1 << 64:
                raise ValueError('invalid native segment extent')
            seg = dict(name=name.rstrip(b'\0').decode(), va=va, size=span, fileoff=off,
                       filesize=backed, maxprot=maximum, initprot=initial, sections=[])
            for index in range(sections):
                name, _, addr, extent, offset = struct.unpack_from('<16s16sQQI', data, pos + 72 + 80 * index)
                if extent and not va <= addr < addr + extent <= va + span:
                    raise ValueError('native section outside segment')
                seg['sections'].append(dict(name=name.rstrip(b'\0').decode(), va=addr, size=extent, fileoff=offset))
            result['segments'].append(seg)
        pos += length
    if pos != end:
        raise ValueError('native command count disagrees with extent')
    return result


def symbols(path: Path) -> dict:
    data = path.read_bytes()
    image = macho(data)
    tables = [at for cmd, at, length in image['commands'] if cmd == 2 and length == 24]
    if len(tables) != 1:
        raise ValueError('requires exactly one native symbol table')
    off, count, strings, size = struct.unpack_from('<4I', data, tables[0] + 8)
    if off + count * 16 > len(data) or strings + size > len(data):
        raise ValueError('native symbol table outside file')
    names, found = data[strings:strings + size], {}
    for index in range(count):
        name, kind, _, _, address = struct.unpack_from('<IBBHQ', data, off + 16 * index)
        if kind & 0xe0 or kind & 0xe != 0xe:
            continue
        end = names.find(b'\0', name)
        if name >= size or end < 0:
            raise ValueError('unterminated native symbol')
        found[names[name:end].decode()] = address
    return found
