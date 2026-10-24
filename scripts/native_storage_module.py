#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve a standalone ARM64E transport into the native prelink address space.

Chained layouts follow the paired dyld/include/mach-o/fixup-chains.h.
Authentication metadata is carried into XNU's format-7 signer.
"""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess

from native_macho import macho, symbols
from inspect_macos26_security import backed_offset, chains, exports, macho as kc_macho

PAGE = 16384


def align(value):
    return (value + PAGE - 1) & -PAGE


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def prepare(directory: Path, base: int, native: dict, original: bytes,
            kc: dict, selected: dict, slide: int) -> dict:
    evidence = json.loads((directory / 'build.json').read_text())
    binary = directory / 'NativeVirtioBlock.macho'
    data = binary.read_bytes()
    if evidence['binary_sha256'] != hashlib.sha256(data).hexdigest():
        raise ValueError('transport differs from its actual build record')
    image = macho(data, 'arm64e')
    if (image['kind'] != 11 or not image['subtype'] & 0x40000000
            or any(s['va'] % PAGE or s['size'] % PAGE for s in image['segments'])):
        raise ValueError('requires a page-aligned standalone ARM64E bundle')
    text = next(s for s in image['segments'] if s['name'] == '__TEXT')
    if text['va'] != 0 or text['fileoff'] != 0 or text['initprot'] not in (1, 5):
        raise ValueError('unexpected standalone transport text mapping')
    info = plistlib.loads((directory / 'Info.plist').read_bytes())
    if info['CFBundleIdentifier'] != evidence['bundle']:
        raise ValueError('transport bundle identity mismatch')
    from build_macos26_storage import PROTOCOL_CHARACTERISTICS
    personality = info['IOKitPersonalities']['NativeVirtioBlock']
    existing = personality.get('Protocol Characteristics')
    if existing is not None and existing != PROTOCOL_CHARACTERISTICS:
        raise ValueError('transport describes a different physical interconnect')
    # VirtIO实际是虚拟块设备，APFS据此选择BaseSystem根卷路径
    personality['Protocol Characteristics'] = dict(PROTOCOL_CHARACTERISTICS)

    if 'com.apple.iokit.IOStorageFamily' not in selected:
        raise ValueError('transport needs the original IOStorageFamily dependency')
    own = symbols(binary)
    if '_kmod_info' not in own:
        raise ValueError('transport has no real kmod descriptor')
    imported = {}
    for name in selected:
        module = kc_macho(original, kc['entries'][name][1])
        for address, names in exports(original, module).items():
            for symbol in names:
                imported.setdefault(symbol, set()).add(address + slide)

    def resolve(name):
        targets = {native[name]} if name in native else imported.get(name, set())
        if len(targets) != 1:
            raise ValueError(f'ambiguous or unavailable transport import: {name}')
        return next(iter(targets))

    command = next(p for c, p, _ in image['commands'] if c == 0x80000034)
    offset, size = struct.unpack_from('<II', data, command + 8)
    if offset + size > len(data) or size < 28:
        raise ValueError('transport fixups exceed file')
    blob = data[offset:offset + size]
    version, starts, imports_at, strings_at, count, fmt, symbols_fmt = struct.unpack_from('<7I', blob)
    if version or symbols_fmt or fmt not in (1, 2, 3) or count > 65536:
        raise ValueError('unsupported transport import table')
    stride = {1: 4, 2: 8, 3: 16}[fmt]
    if imports_at + count * stride > len(blob) or strings_at > len(blob):
        raise ValueError('transport imports exceed fixups')
    imports = []
    for i in range(count):
        p = imports_at + i * stride
        raw, = struct.unpack_from('<Q' if fmt == 3 else '<I', blob, p)
        name_offset = raw >> (32 if fmt == 3 else 9)
        ordinal = signed(raw & (0xffff if fmt == 3 else 0xff), 16 if fmt == 3 else 8)
        weak = bool(raw >> (16 if fmt == 3 else 8) & 1)
        if ordinal not in (-2, -3) or weak:
            raise ValueError('transport requires explicit nonweak flat imports')
        p = strings_at + name_offset
        end = blob.find(b'\0', p)
        if not strings_at <= p < end < len(blob):
            raise ValueError('unterminated transport import')
        name = blob[p:end].decode()
        addend = 0 if fmt == 1 else struct.unpack_from('<q' if fmt == 3 else '<i', blob,
                                                       imports_at + i * stride + stride // 2)[0]
        imports.append((name, resolve(name) + addend))
    if starts + 4 > len(blob):
        raise ValueError('transport chain starts exceed fixups')
    segments, = struct.unpack_from('<I', blob, starts)
    if segments != len(image['segments']) or starts + 4 + segments * 4 > len(blob):
        raise ValueError('transport chain segment count mismatch')
    relocations, seen, formats = [], set(), set()
    for i, seg in enumerate(image['segments']):
        relative, = struct.unpack_from('<I', blob, starts + 4 + i * 4)
        if not relative:
            continue
        p = starts + relative
        if p + 22 > len(blob):
            raise ValueError('transport segment chain header exceeds fixups')
        length, page_size, pointer_format, segment_offset, _, pages = struct.unpack_from('<IHHQIH', blob, p)
        if (pointer_format not in (1, 7, 9, 12) or page_size not in (4096, PAGE)
                or segment_offset != seg['va'] or length < 22 + pages * 2
                or p + length > len(blob) or pages * page_size > seg['size']):
            raise ValueError('unsupported transport pointer chain layout')
        formats.add(pointer_format)
        for page in range(pages):
            first, = struct.unpack_from('<H', blob, p + 22 + page * 2)
            if first == 0xffff:
                continue
            if first & 0x8000:
                raise ValueError('transport multi-start chain is unsupported')
            site = seg['va'] + page * page_size + first
            while True:
                bottom = seg['va'] + page * page_size
                if site in seen or site & 3 or not bottom <= site < bottom + page_size:
                    raise ValueError('transport chain repeats or crosses its page')
                seen.add(site)
                at = backed_offset(image['segments'], site, 8, len(data))
                word, = struct.unpack_from('<Q', data, at)
                auth, bind = bool(word >> 63), bool(word >> 62 & 1)
                name = None
                if bind:
                    bits = 24 if pointer_format == 12 else 16
                    index = word & ((1 << bits) - 1)
                    if index >= len(imports) or word >> bits & ((1 << (32 - bits)) - 1):
                        raise ValueError('invalid transport bind ordinal')
                    name, target = imports[index]
                    if not auth:
                        target += signed(word >> 32 & 0x7ffff, 19)
                else:
                    if not auth and word >> 43 & 0xff:
                        raise ValueError('tagged transport rebase is unsupported')
                    target = base + (word & (0xffffffff if auth else (1 << 43) - 1))
                    if not any(base + s['va'] <= target <= base + s['va'] + s['size']
                               for s in image['segments']):
                        raise ValueError('transport rebase target is outside the module')
                relocations.append(dict(new_site=base + site, new_target=target,
                    authenticated=auth, key=(word >> 49) & 3,
                    address_diversity=bool(word >> 48 & 1), diversity=word >> 32 & 0xffff,
                    import_name=name))
                following = word >> 51 & 0x7ff
                if not following:
                    break
                site += following * (4 if pointer_format == 7 else 8)
    reserved = '__ZN15OSMetaClassBase25_RESERVEDOSMetaClassBase3Ev'
    dispatch = '__ZN15OSMetaClassBase8DispatchE5IORPC'
    slots = {base + address + 16 + 16 * 8 for name, address in own.items() if name.startswith('__ZTV')}
    compatibility = []
    for item in relocations:
        if item['import_name'] != reserved:
            continue
        if item['new_site'] not in slots or dispatch not in native:
            raise ValueError('unexpected reserved Dispatch compatibility use')
        compatibility.append(dict(site=item['new_site'], previous_target=item['new_target'],
                                  target=native[dispatch], original_symbol=reserved, runtime_symbol=dispatch))
        item['new_target'] = native[dispatch]
    driver = dict(data=data, image=image, base=base, header_va=base, info=info,
                kmod=base + own['_kmod_info'], symbols={n: a + base for n, a in own.items()},
                relocations=relocations, imports=dict(imports), pointer_formats=sorted(formats),
                evidence=evidence, compatibility=compatibility)
    driver['vtable_abi'] = audit_storage_vtable(driver, original, kc, native, slide)
    return driver


def audit_storage_vtable(driver: dict, original: bytes, kc: dict, native: dict, slide: int) -> dict:
    family = kc_macho(original, kc['entries']['com.apple.iokit.IOStorageFamily'][1])
    kernel = kc_macho(original, kc['entries']['com.apple.kernel'][1])
    old_names = exports(original, kernel)
    old_names.update(exports(original, family))
    table = next(a for a, names in exports(original, family).items()
                 if '__ZTV20IOBlockStorageDevice' in names)
    original_slots = {p['site']: p for p in chains(original, kc)}
    own_table = driver['symbols']['__ZTV17NativeVirtioBlock']
    own_slots = {p['new_site']: p for p in driver['relocations']}
    own_names = {}
    for name, address in driver['symbols'].items():
        own_names.setdefault(address, []).append(name)

    tool = shutil.which('llvm-cxxfilt') or shutil.which('c++filt')
    if not tool:
        raise ValueError('vtable ABI comparison needs an Itanium C++ demangler')
    relevant = list(dict.fromkeys([n for i in range(512)
        for n in old_names.get(original_slots.get(table + 16 + i * 8, {}).get('target'), [])]
        + [n for names in own_names.values() for n in names]))
    decoded = subprocess.check_output([tool], input='\n'.join(
        n[1:] if n.startswith('__Z') else n for n in relevant) + '\n', text=True).splitlines()
    if len(decoded) != len(relevant):
        raise ValueError('incomplete vtable symbol demangling')
    methods = {n: d.split('::', 1)[1] if '::' in d else None for n, d in zip(relevant, decoded)}

    slots, overrides = [], 0
    for index in range(512):
        old = original_slots.get(table + 16 + index * 8)
        own = own_slots.get(own_table + 16 + index * 8)
        if old is None or own is None:
            if old is not None or own is not None or index == 0:
                raise ValueError('transport/base vtable slot count differs')
            break
        names = old_names.get(old['target'], [])
        expected = {native[n] for n in names if n in native}
        expected.add(old['target'] + slide)
        override = own['new_target'] in own_names and any(
            n.startswith(('__ZN17NativeVirtioBlock', '__ZNK17NativeVirtioBlock'))
            for n in own_names[own['new_target']])
        if override:
            actual = own_names[own['new_target']]
            if index not in (0, 1) and '___cxa_pure_virtual' not in names and not any(
                    methods[n] is not None and methods[n] == methods[a] for n in names for a in actual):
                raise ValueError(f'transport override ABI mismatch at slot {index}: {names} / {actual}')
            overrides += 1
        elif own['new_target'] not in expected:
            raise ValueError(f'transport inherited vtable ABI mismatch at slot {index}: {names}')
        for key in ('authenticated', 'key', 'diversity', 'address_diversity'):
            if own[key] != old[key]:
                raise ValueError(f'transport vtable PAC contract differs at slot {index}: {key}')
        slots.append(dict(slot=index, original_names=names, own_names=own_names.get(own['new_target']),
                          target=hex(own['new_target']), override=override))
    else:
        raise ValueError('unbounded transport vtable')
    return dict(slots=len(slots), overrides=overrides, pac_metadata_matches=True, methods=slots)


def rewrite_header(driver, output, at):
    data, image, base = driver['data'], driver['image'], driver['base']
    header = at(base, 32)
    struct.pack_into('<I', output, header + 12, 11)  # MH_KEXT_BUNDLE
    flags, = struct.unpack_from('<I', output, header + 24)
    struct.pack_into('<I', output, header + 24, flags | 0x80000000)  # VM-address cache view

    def translated(offset):
        found = [s for s in image['segments'] if s['fileoff'] <= offset < s['fileoff'] + s['filesize']]
        if len(found) != 1:
            raise ValueError('transport linkedit offset is not file-backed')
        return at(base + found[0]['va'] + offset - found[0]['fileoff'], 1)

    for cmd, pos, length in image['commands']:
        p = at(base + pos, length)
        if cmd == 0x19:
            name = data[pos + 8:pos + 24].rstrip(b'\0').decode()
            s = next(s for s in image['segments'] if s['name'] == name)
            struct.pack_into('<QQQ', output, p + 24, base + s['va'], s['size'], at(base + s['va'], 1))
            for i, section in enumerate(s['sections']):
                sec = p + 72 + i * 80
                struct.pack_into('<Q', output, sec + 32, base + section['va'])
                if section['fileoff'] and section['size']:
                    struct.pack_into('<I', output, sec + 48, at(base + section['va'], 1))
        elif cmd == 2:
            symoff, count, strings, _ = struct.unpack_from('<4I', data, pos + 8)
            struct.pack_into('<I', output, p + 8, translated(symoff))
            struct.pack_into('<I', output, p + 16, translated(strings))
            for i in range(count):
                row = symoff + i * 16
                _, kind, _, _, value = struct.unpack_from('<IBBHQ', data, row)
                if not kind & 0xe0 and kind & 0xe == 0xe:
                    struct.pack_into('<Q', output, translated(row) + 8, base + value)
        elif cmd == 0xb:
            for field in (32, 40, 48, 56, 64, 72):
                old, = struct.unpack_from('<I', data, pos + field)
                if old:
                    struct.pack_into('<I', output, p + field, translated(old))
        elif cmd in (0x1d, 0x1e, 0x26, 0x29, 0x2b, 0x80000033, 0x80000034):
            old, size = struct.unpack_from('<II', data, pos + 8)
            if size:
                struct.pack_into('<I', output, p + 8, translated(old))
    if not any(c == 0x1e for c, _, _ in image['commands']):
        count, size = struct.unpack_from('<II', output, header + 16)
        p = header + 32 + size
        first = min(s['fileoff'] for seg in image['segments'] for s in seg['sections'] if s['size'])
        if 32 + size + 16 > first or any(output[p:p + 16]):
            raise ValueError('transport lacks verified split-info header padding')
        struct.pack_into('<4I', output, p, 0x1e, 16, 0, 0)
        struct.pack_into('<II', output, header + 16, count + 1, size + 16)
    extent = max(s['va'] + s['size'] for s in image['segments'])
    text = next(s for s in image['segments'] if s['name'] == '__TEXT')
    struct.pack_into('<QQQ', output, at(driver['kmod'] + 156, 24), base, extent, text['size'])
