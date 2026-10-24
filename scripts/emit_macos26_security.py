#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Emit a QEMU-only ARM64E prelink candidate with real security components."""
import argparse
import copy
from collections import defaultdict
import hashlib
import hmac
import json
from pathlib import Path
import plistlib
import shutil
import struct
import sys
import xml.etree.ElementTree as ET

from inspect_macos26_security import ROOT, ROOTS, backed_offset, macho as kc_macho
from native_macho import macho, native_chained_fixups
from observe_macos26_kernel import identify
from plan_macos26_security import MASK64, plan

sys.path.insert(0, str(ROOT / 'UniXNU/kits/NativePrelink'))
from emit_prelink import to_xml

BASE = 0xfffffe0007004000
PAGE = 16384
GROUPS = {'__PRELINK_TEXT': '__TEXT', '__PLK_TEXT_EXEC': '__TEXT_EXEC',
          '__PLK_DATA_CONST': '__DATA_CONST', '__PRELINK_DATA': '__DATA',
          '__PLK_LINKEDIT': '__LINKEDIT', '__PLK_LINKINFO': '__LINKINFO'}


def align(value, boundary=PAGE):
    return (value + boundary - 1) & -boundary


def native_pointers(data, image):
    native_chained_fixups(data)
    at = next(o for c, o, _ in image['commands'] if c == 0x80000034)
    offset, _ = struct.unpack_from('<II', data, at + 8)
    starts = offset + struct.unpack_from('<I', data, offset + 4)[0]
    for i, segment in enumerate(image['segments']):
        relative, = struct.unpack_from('<I', data, starts + 4 + i * 4)
        if not relative:
            continue
        header = starts + relative
        _, page_size, _, _, _, pages = struct.unpack_from('<IHHQIH', data, header)
        for page in range(pages):
            first, = struct.unpack_from('<H', data, header + 22 + page * 2)
            if first == 0xffff:
                continue
            site = segment['va'] + page * page_size + first
            while True:
                at = backed_offset(image['segments'], site, 8, len(data))
                raw, = struct.unpack_from('<Q', data, at)
                auth = bool(raw >> 63)
                if not auth and (raw >> 43) & 0xff:
                    raise ValueError('tagged native pointer needs an explicit high-byte relocation')
                yield dict(new_site=site, new_target=BASE + (raw & (0xffffffff if auth else (1 << 43) - 1)),
                           authenticated=auth, key=(raw >> 49) & 3,
                           address_diversity=bool((raw >> 48) & 1), diversity=(raw >> 32) & 0xffff)
                following = (raw >> 51) & 0x7ff
                if not following:
                    break
                site += following * 4


def segment_command(name, va, size, fileoff, protection, sections=()):
    return bytearray(struct.pack('<II16s4Q4I', 0x19, 72 + len(sections) * 80,
        name.encode(), va, size, fileoff, size, protection, protection, len(sections), 0)
        + b''.join(sections))


def section_command(name, segment, va, size, fileoff):
    return struct.pack('<16s16sQQ8I', name.encode(), segment.encode(), va, size,
                       fileoff, 3, 0, 0, 0, 0, 0, 0)


def chain_blob(segments, relocations):
    by_segment = [defaultdict(list) for _ in segments]
    for r in relocations:
        site = r['new_site']
        matches = [i for i, s in enumerate(segments) if s['va'] <= site and site + 8 <= s['va'] + s['filesize']]
        if len(matches) != 1 or site & 3:
            raise ValueError(f'pointer outside one mapped segment: {site:#x}')
        i = matches[0]
        by_segment[i][(site - segments[i]['va']) // 4096].append(r)
    starts = bytearray(struct.pack('<I', len(segments)) + bytes(4 * len(segments)))
    writes = []
    for i, pages in enumerate(by_segment):
        if not pages:
            continue
        s = segments[i]
        count = s['size'] // 4096
        if count > 0xffff:
            raise ValueError('too many chained-fixup pages')
        struct.pack_into('<I', starts, 4 + i * 4, len(starts))
        firsts = [0xffff] * count
        for page, entries in sorted(pages.items()):
            entries.sort(key=lambda r: r['new_site'])
            firsts[page] = entries[0]['new_site'] - s['va'] - page * 4096
            for j, r in enumerate(entries):
                distance = entries[j + 1]['new_site'] - r['new_site'] if j + 1 < len(entries) else 0
                if distance and (distance < 8 or distance % 4 or distance // 4 > 0x7ff):
                    raise ValueError('overlapping pointers or unsupported chain stride')
                target = r['new_target'] - BASE
                if not 0 <= target < (1 << (32 if r['authenticated'] else 43)):
                    raise ValueError('pointer target cannot be encoded')
                raw = target | ((distance // 4) << 51)
                if r['authenticated']:
                    raw |= (1 << 63) | (r['key'] << 49) | (int(r['address_diversity']) << 48) | (r['diversity'] << 32)
                writes.append((r['new_site'], raw))
        starts.extend(struct.pack('<IHHQIH', 22 + 2 * count, 4096, 7, s['va'] - BASE, 0, count))
        starts.extend(struct.pack(f'<{count}H', *firsts))
    return struct.pack('<7I', 0, 28, 0, 0, 0, 0, 0) + starts, writes


def emit(native_data, original, native_names, identity, slide, roots=ROOTS, storage_driver=None):
    image = macho(native_data, 'arm64e')
    marker = native_names.get('_sheng_security_prelink_version')
    if marker is None or struct.unpack_from('<I', native_data,
            backed_offset(image['segments'], marker, 4, len(native_data)))[0] != 1:
        raise ValueError('kernel lacks the sparse security prelink contract')
    report = plan(original, native_names, identity, slide, roots)
    if report['instruction_blockers']:
        raise ValueError('instruction relocation has unresolved blockers')
    kc = kc_macho(original)
    selected = report['modules']
    modules = {n: kc_macho(original, kc['entries'][n][1]) for n in selected}
    info_section = next(sec for s in kc['segments'] if s['name'] == '__PRELINK_INFO'
                        for sec in s['sections'] if sec['name'] == '__info')
    info_at = backed_offset(kc['segments'], info_section['va'], info_section['size'], len(original))
    metadata = plistlib.loads(original[info_at:info_at + info_section['size']].split(b'\0', 1)[0])
    entries = {e['CFBundleIdentifier']: e for e in metadata['_PrelinkInfoDictionary']}
    driver = None
    if storage_driver is not None:
        from native_storage_module import prepare
        text_end = align(max(s['va'] + s['size'] for m in modules.values()
                             for s in m['segments'] if s['name'] == '__TEXT')) + slide
        driver = prepare(storage_driver, text_end, native_names, original, kc, selected, slide)
    segments = copy.deepcopy(image['segments'])
    pending = {}
    text_section_start = 0
    for target, source in GROUPS.items():
        parts = [s for m in modules.values() for s in m['segments'] if s['name'] == source and s['size']]
        if not parts:
            continue
        low = min(s['va'] for s in parts) & -PAGE
        high = align(max(s['va'] + s['size'] for s in parts))
        if low + slide < BASE or high + slide > BASE + 0x20000000:
            raise ValueError('coalesced component group exceeds the owned memory window')
        blob = bytearray(high - low)
        for s in parts:
            blob[s['va'] - low:s['va'] - low + s['filesize']] = original[s['fileoff']:s['fileoff'] + s['filesize']]
        if target == '__PRELINK_TEXT':
            headers = sorted(kc['entries'][n][0] + slide for n in modules)
            if driver:
                own_text = next(s for s in driver['image']['segments'] if s['name'] == '__TEXT')
                headers.append(driver['header_va'])
                table = struct.pack(f'<{len(headers)}Q', *headers)
                prefix = min(s['va'] for s in parts) - low
                if prefix < len(table) or any(blob[:len(table)]):
                    raise ValueError('no verified prefix padding for the transport header index')
                index_offset = 0
                text_section_start = align(len(table), 8)
                blob[:len(table)] = table
                blob.extend(bytes(driver['base'] - (low + slide) - len(blob)))
                blob.extend(driver['data'][:own_text['filesize']])
                blob.extend(bytes(own_text['size'] - own_text['filesize']))
            else:
                index_offset = align(len(blob), 8)
                blob.extend(bytes(index_offset - len(blob)))
                blob.extend(struct.pack(f'<{len(headers)}Q', *headers))
        blob.extend(bytes(align(len(blob)) - len(blob)))
        protection = 5 if source == '__TEXT_EXEC' else 3 if source == '__DATA' else 1
        if driver and source == '__TEXT':
            protection |= own_text['initprot'] & 4
        record = dict(name=target, va=low + slide, size=len(blob), filesize=len(blob),
                      fileoff=0, initprot=protection, maxprot=protection, sections=[])
        existing = next((s for s in segments if s['name'] == target), None)
        if existing:
            if existing['size']:
                raise ValueError(f'prelink placeholder already populated: {target}')
            existing.update(record)
        else:
            segments.append(record)
        pending[target] = blob

    if driver:
        for s in driver['image']['segments']:
            if s['name'] == '__TEXT' or not s['size']:
                continue
            name = '__NVB_' + s['name'].strip('_')
            if len(name) > 16:
                raise ValueError('transport segment name exceeds Mach-O width')
            blob = bytearray(driver['data'][s['fileoff']:s['fileoff'] + s['filesize']])
            blob.extend(bytes(s['size'] - len(blob)))
            segments.append(dict(name=name, va=driver['base'] + s['va'], size=s['size'],
                filesize=s['size'], fileoff=0, initprot=s['initprot'], maxprot=s['maxprot'], sections=[]))
            pending[name] = blob

    # Read local registration symbols from each selected image's own symbol slice.
    registration_symbols = {}
    early_initializers = {}
    registration_names = {
        'com.apple.security.AppleImage4': b'_kmod_link_init',
        'com.apple.driver.AppleMobileFileIntegrity': b'_amfi_register_mac_policy',
    }
    symbol_slices = []
    for n, module in modules.items():
        at = next(o for c, o, _ in module['commands'] if c == 2)
        symoff, count, stroff, strsize = struct.unpack_from('<4I', original, at + 8)
        strings = original[stroff:stroff + strsize]
        symbol_slices.append((symoff, count))
        for index in range(count):
            strx, kind, _, _, address = struct.unpack_from('<IBBHQ', original, symoff + index * 16)
            end = strings.find(b'\0', strx)
            if (not kind & 0xe0 and kind & 0xe == 0xe
                    and strings[strx:end] == registration_names.get(n)):
                if n in registration_symbols:
                    raise ValueError(f'ambiguous original security registration symbol: {n}')
                registration_symbols[n] = address + slide
    amfi = 'com.apple.driver.AppleMobileFileIntegrity'
    if amfi not in registration_symbols:
        raise ValueError('matched AMFI has no original policy registration entry')
    early_initializers[amfi] = registration_symbols[amfi]

    selected_entries = []
    for n in [*report['kernel_interfaces'], *sorted(modules)]:
        entry = copy.deepcopy(entries[n])
        if n in modules:
            for key in ('_PrelinkExecutableLoadAddr', '_PrelinkExecutableSourceAddr', '_PrelinkKmodInfo'):
                entry[key] = (entry[key] & MASK64) + slide
            # Image4 registers during normal start; AMFI's null __realmain
            # requires its real policy entry before MAC lockdown.
            entry.pop('_NativePrelinkEarlySecurityInit', None)
            if n in early_initializers:
                if entry.get('AppleSecurityExtension') is not True:
                    raise ValueError(f'early policy entry is not a security extension: {n}')
                entry['_NativePrelinkEarlySecurityInit'] = early_initializers[n]
        selected_entries.append(entry)
    if driver:
        entry = copy.deepcopy(driver['info'])
        entry.update(_PrelinkExecutableLoadAddr=driver['header_va'],
                     _PrelinkExecutableSourceAddr=driver['header_va'],
                     _PrelinkExecutableSize=max(s['va'] + s['size'] for s in driver['image']['segments']),
                     _PrelinkKmodInfo=driver['kmod'],
                     _PrelinkBundlePath='/System/Library/Extensions/NativeVirtioBlock.kext')
        selected_entries.append(entry)
    cache_id = hashlib.sha256(native_data + original + struct.pack('<Q', slide)
                              + '\0'.join(sorted(modules)).encode()
                              + (driver['data'] if driver else b'')).digest()[:16]
    xml = ET.tostring(to_xml(dict(_PrelinkInfoDictionary=selected_entries,
                                 _PrelinkLinkKASLROffsets=bytes(4), _PrelinkKCID=cache_id)),
                      encoding='utf-8').replace(b' />', b'/>') + b'\0'
    info_va = align(max(s['va'] + s['size'] for s in segments if s['size']))
    blob = bytearray(xml)
    crypto_offset = align(len(blob), 8)
    blob.extend(bytes(crypto_offset - len(blob)))
    blob.extend(struct.pack('<Q', (entries['com.apple.kec.corecrypto']['_PrelinkKmodInfo'] & MASK64) + slide))
    blob.extend(bytes(align(len(blob)) - len(blob)))
    info = next(s for s in segments if s['name'] == '__PRELINK_INFO')
    info.update(va=info_va, size=len(blob), filesize=len(blob), fileoff=0, initprot=3, maxprot=3)
    pending['__PRELINK_INFO'] = blob

    # Chain metadata is mapped at the end of the native LINKEDIT, before appending modules.
    relocations = list(native_pointers(native_data, image)) + report['pointer_relocations']
    if driver:
        relocations += driver['relocations']
    fixups, writes = chain_blob(segments, relocations)
    output = bytearray(native_data)
    fixup_at = align(len(output), 8)
    output.extend(bytes(fixup_at - len(output)))
    output.extend(fixups)
    linkedit = next(s for s in segments if s['name'] == '__LINKEDIT')
    linkedit['filesize'] = len(output) - linkedit['fileoff']
    linkedit['size'] = align(linkedit['filesize'])
    for name, blob in pending.items():
        at = align(len(output))
        output.extend(bytes(at - len(output)))
        output.extend(blob)
        next(s for s in segments if s['name'] == name)['fileoff'] = at
    occupied = sorted((s['va'], s['va'] + s['size']) for s in segments if s['size'])
    if any(a[1] > b[0] for a, b in zip(occupied, occupied[1:])) or occupied[-1][1] - BASE > 0x20000000:
        raise ValueError('coalesced candidate has overlapping mappings or exceeds its memory window')

    def at(address, length=8):
        return backed_offset(segments, address, length, len(output))

    def translate_file(offset):
        matches = [s for s in kc['segments'] if s['fileoff'] <= offset < s['fileoff'] + s['filesize']]
        if len(matches) != 1:
            raise ValueError('module linkedit offset is not backed')
        old = matches[0]
        return at(old['va'] + offset - old['fileoff'] + slide, 1)

    if driver:
        from native_storage_module import rewrite_header
        rewrite_header(driver, output, at)

    # Numeric header addresses and kmod_info.address are not chained pointers.
    for n, module in modules.items():
        old_header = kc['entries'][n][0]
        header_at = at(old_header + slide, 32)
        # Apple components use MH_DYLIB_IN_CACHE to select VM-address-based
        # metadata, including corecrypto's original integrity walker.
        for command, pos, length in module['commands']:
            new_pos = at(old_header + slide + pos - kc['entries'][n][1], length)
            if command == 0x19:
                name = original[pos + 8:pos + 24].rstrip(b'\0').decode()
                s = next(s for s in module['segments'] if s['name'] == name)
                struct.pack_into('<QQQ', output, new_pos + 24, s['va'] + slide, s['size'], at(s['va'] + slide, 1))
                for i, section in enumerate(s['sections']):
                    secpos = new_pos + 72 + i * 80
                    struct.pack_into('<Q', output, secpos + 32, section['va'] + slide)
                    if section['fileoff']:
                        struct.pack_into('<I', output, secpos + 48, at(section['va'] + slide, 1))
            elif command == 2:
                for field in (8, 16):
                    old, = struct.unpack_from('<I', original, pos + field)
                    struct.pack_into('<I', output, new_pos + field, translate_file(old))
            elif command == 0xb:
                for field in (32, 40, 48, 56, 64, 72):
                    old, = struct.unpack_from('<I', original, pos + field)
                    if old:
                        struct.pack_into('<I', output, new_pos + field, translate_file(old))
            elif command in (0x1d, 0x1e, 0x26, 0x29, 0x2b, 0x80000033, 0x80000034):
                old, size = struct.unpack_from('<II', original, pos + 8)
                if size:
                    struct.pack_into('<I', output, new_pos + 8, translate_file(old))
        kmod = (entries[n]['_PrelinkKmodInfo'] & MASK64) + slide
        struct.pack_into('<Q', output, at(kmod + 156), old_header + slide)
        if not any(command == 0x1e for command, _, _ in module['commands']):
            count, size = struct.unpack_from('<II', output, header_at + 16)
            first_section = min(sec['va'] for seg in module['segments'] if seg['name'] == '__TEXT'
                                for sec in seg['sections'] if sec['size'])
            marker_at = header_at + 32 + size
            if first_section - old_header < 32 + size + 16 or any(output[marker_at:marker_at + 16]):
                raise ValueError('no verified header padding for split-segment descriptor')
            # All relocations are carried by the outer format-7 table. An empty
            # legacy split-info command describes the already split mappings.
            struct.pack_into('<4I', output, marker_at, 0x1e, 16, 0, 0)
            struct.pack_into('<II', output, header_at + 16, count + 1, size + 16)

    for symoff, count in symbol_slices:
        for i in range(count):
            old_at = symoff + i * 16
            _, kind, _, _, value = struct.unpack_from('<IBBHQ', original, old_at)
            if kind & 0xe0 or kind & 0xe != 0xe:
                continue
            if any(s['va'] <= value < s['va'] + s['size'] for m in modules.values()
                   for s in m['segments'] if s['name'] != '__LINKEDIT'):
                struct.pack_into('<Q', output, translate_file(old_at) + 8, value + slide)
    for address, raw in writes:
        struct.pack_into('<Q', output, at(address), raw)
    for patch in report['branch_relocations']:
        pos = at(patch['new_site'], 4)
        if struct.unpack_from('<I', output, pos)[0] != patch['word']:
            raise ValueError('branch source word changed during emission')
        struct.pack_into('<I', output, pos, patch['replacement'])

    crypto = modules['com.apple.kec.corecrypto']
    text = next(sec for s in crypto['segments'] for sec in s['sections'] if sec['name'] == '__text')
    integrity = next(sec for s in crypto['segments'] for sec in s['sections'] if sec['name'] == '__fips_hmacs')
    if integrity['size'] != 32 or hmac.digest(bytes(32), original[text['fileoff']:text['fileoff'] + text['size']], 'sha256') != original[integrity['fileoff']:integrity['fileoff'] + 32]:
        raise ValueError('original corecrypto integrity contract differs')
    digest = hmac.digest(bytes(32), output[at(text['va'] + slide, text['size']):at(text['va'] + slide, text['size']) + text['size']], 'sha256')
    output[at(integrity['va'] + slide, 32):at(integrity['va'] + slide, 32) + 32] = digest

    commands = []
    for command, pos, length in image['commands']:
        raw = bytearray(output[pos:pos + length])
        if command == 0x19:
            name = raw[8:24].rstrip(b'\0').decode()
            s = next(s for s in segments if s['name'] == name)
            if name in pending:
                start = text_section_start if name == '__PRELINK_TEXT' else 0
                section_size = s['size']
                if name == '__PRELINK_INFO':
                    section_size = len(xml)
                elif name == '__PRELINK_TEXT':
                    section_size = s['size'] - start if driver else index_offset
                sections = [section_command('__info' if name == '__PRELINK_INFO' else '__text' if name == '__PRELINK_TEXT' else '__data', name, s['va'] + start, section_size, s['fileoff'] + start)]
                if name == '__PRELINK_TEXT':
                    sections.append(section_command('__macho_list', name, s['va'] + index_offset,
                        len(headers) * 8, s['fileoff'] + index_offset))
                if name == '__PRELINK_INFO':
                    sections.append(section_command('__crypto_early', name, s['va'] + crypto_offset,
                        8, s['fileoff'] + crypto_offset))
                raw = segment_command(name, s['va'], s['size'], s['fileoff'], s['initprot'], sections)
            elif name == '__LINKEDIT':
                struct.pack_into('<QQQQ', raw, 24, s['va'], s['size'], s['fileoff'], s['filesize'])
        elif command == 0x80000034:
            struct.pack_into('<II', raw, 8, fixup_at, len(fixups))
        commands.append(raw)
    for s in segments[len(image['segments']):]:
        commands.append(segment_command(s['name'], s['va'], s['size'], s['fileoff'], s['initprot']))
    rebuilt = b''.join(commands)
    first = min(sec['fileoff'] for s in image['segments'] for sec in s['sections'] if sec['size'] and sec['fileoff'])
    if len(rebuilt) + 32 > first:
        raise ValueError('insufficient native load-command padding')
    struct.pack_into('<II', output, 16, len(commands), len(rebuilt))
    output[32:32 + len(rebuilt)] = rebuilt
    final_data = bytes(output)
    for module_at in [0, *(at(kc['entries'][n][0] + slide, 32) for n in modules),
                      *([at(driver['header_va'], 32)] if driver else [])]:
        checked = kc_macho(final_data, module_at)
        for segment in checked['segments']:
            extents = sorted((sec['va'], sec['va'] + sec['size']) for sec in segment['sections'] if sec['size'])
            if any(a[1] > b[0] for a, b in zip(extents, extents[1:])):
                raise ValueError('overlapping sections in the emitted Mach-O')
    crypto_header = at(kc['entries']['com.apple.kec.corecrypto'][0] + slide, 32)
    if not struct.unpack_from('<I', output, crypto_header + 24)[0] & 0x80000000:
        raise ValueError('original corecrypto requires its VM-address-based cache view')
    fixup_summary = native_chained_fixups(final_data)
    report.update(candidate_bytes=len(output), candidate_sha256=hashlib.sha256(output).hexdigest(),
        original_corecrypto_hmac=digest.hex(), native_pointer_fixups=fixup_summary,
        original_security_registration_symbols=registration_symbols,
        early_security_initializers=early_initializers, cache_id=cache_id.hex(),
        source_inputs_modified=False, qemu_only=True, hardware_admitted=False,
        runtime_qualified=False, loadable=False)
    report['pending'] = ['validate instruction dataflow and native callback ABI',
                         'execute original corecrypto POST and PRNG registration',
                         'execute real security constructors and register Image4/AMFI in QEMU']
    if driver:
        report['storage_driver'] = dict(bundle=driver['info']['CFBundleIdentifier'],
            base=driver['base'], kmod=driver['kmod'], symbols=driver['symbols'],
            imports=driver['imports'], pointer_formats=driver['pointer_formats'],
            vtable_abi=driver['vtable_abi'],
            compatibility=driver['compatibility'],
            pointer_count=len(driver['relocations']),
            authenticated_pointers=sum(p['authenticated'] for p in driver['relocations']),
            build=driver['evidence'], runtime_qualified=False)
    return final_data, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--bootkc', type=Path, default=ROOT / 'private/apple/macos26/kernelcache.release.mac13g.decoded')
    parser.add_argument('--slide', type=lambda s: int(s, 0), default=0x2000000)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--qemu-only', action='store_true', required=True)
    parser.add_argument('--include-module', action='append', default=[], metavar='BUNDLE',
                        help='include another original BootKC module and its dependency closure')
    parser.add_argument('--storage-driver', type=Path, help='standalone ARM64E transport build directory')
    args = parser.parse_args()
    try:
        kernel, names, identity = identify(args.kernel_build.resolve())
        candidate, report = emit(kernel.read_bytes(), args.bootkc.read_bytes(), names, identity,
                                 args.slide, (*ROOTS, *args.include_module), args.storage_driver)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / kernel.name).write_bytes(candidate)
        shutil.copytree(args.kernel_build / 'kernel.development.sheng.dSYM', args.output / 'kernel.development.sheng.dSYM')
        shutil.copy2(args.kernel_build / 'kernel.development.sheng.map', args.output / 'kernel.development.sheng.map')
        metadata = json.loads((args.kernel_build / 'build.json').read_text())
        metadata.update(executable_kernel_sha256=report['candidate_sha256'], native_security_candidate=True,
                        source_kernel_sha256=identity['kernel_sha256'], hardware_admitted=False,
                        native_pointer_fixups=report['native_pointer_fixups'])
        (args.output / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
        (args.output / 'security-relink.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: report[k] for k in ('candidate_bytes', 'candidate_sha256', 'native_pointer_fixups', 'qemu_only', 'loadable')}, indent=2))
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
