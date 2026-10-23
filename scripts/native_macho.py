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


def native_chained_fixups(data: bytes) -> dict:
    """Admit the self-contained format-7 rebases consumed before native globals."""
    image = macho(data, 'arm64e')
    commands = [at for cmd, at, size in image['commands'] if cmd == 0x80000034 and size == 16]
    if image['kind'] != 2 or len(commands) != 1:
        raise ValueError('native ARM64E requires one chained-fixups command in MH_EXECUTE')
    off, size = struct.unpack_from('<II', data, commands[0] + 8)
    if size < 28 or off + size > len(data):
        raise ValueError('native chained-fixups data outside file')
    blob = data[off:off + size]
    version, starts, _, _, imports, _, _ = struct.unpack_from('<7I', blob)
    if version or imports or not 28 <= starts <= size - 4:
        raise ValueError('native boot fixups must be self-contained rebases without imports')
    count, = struct.unpack_from('<I', blob, starts)
    if count != len(image['segments']) or starts + 4 + count * 4 > size:
        raise ValueError('native fixup segment count differs from Mach-O')
    base = next(segment['va'] for segment in image['segments'] if segment['name'] == '__TEXT')
    visited, authenticated = set(), 0
    for index, segment in enumerate(image['segments']):
        relative, = struct.unpack_from('<I', blob, starts + 4 + index * 4)
        if not relative:
            continue
        pos = starts + relative
        if pos + 22 > size:
            raise ValueError('native fixup starts outside metadata')
        span, page_size, fmt, offset, _, pages = struct.unpack_from('<IHHQIH', blob, pos)
        if (fmt != 7 or page_size not in (4096, 16384) or span < 22 + 2 * pages
                or pos + span > size or base + offset != segment['va']
                or pages * page_size > segment['size']):
            raise ValueError('native startup requires bounded format-7 segment chains')
        for page in range(pages):
            start, = struct.unpack_from('<H', blob, pos + 22 + 2 * page)
            if start == 0xffff:
                continue
            if start & 0x8000:
                raise ValueError('native startup does not support multi-start chains')
            site = page * page_size + start
            while True:
                if (not page * page_size <= site < (page + 1) * page_size
                        or site & 3 or site + 8 > segment['filesize']
                        or segment['fileoff'] + site + 8 > len(data)
                        or (index, site) in visited):
                    raise ValueError('native pointer chain exceeds its backing segment or page')
                visited.add((index, site))
                raw, = struct.unpack_from('<Q', data, segment['fileoff'] + site)
                if raw >> 62 & 1:
                    raise ValueError('unresolved native bind before global initialization')
                auth = raw >> 63
                target = base + (raw & (0xffffffff if auth else (1 << 43) - 1))
                if not any(s['va'] <= target <= s['va'] + s['size']
                           for s in image['segments'] if s['size']):
                    raise ValueError('native fixup target outside linked image')
                authenticated += auth
                following = raw >> 51 & 0x7ff
                if not following:
                    break
                site += following * 4
    if not authenticated:
        raise ValueError('native ARM64E has no authenticated pointer fixups')
    return dict(format=7, pointers=len(visited), authenticated=authenticated,
                signer='XNU native kernel_collection_slide before global initialization')
