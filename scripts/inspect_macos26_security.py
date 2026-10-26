#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locate the real BootKC security dependencies and their native ABI boundaries.

Read-only. Format-8 chain words retain their PAC key, diversity and address
discriminator. No unsigned pointer image or executable candidate is produced.
Reference: Snapintosh probes/auxkc.py and XNU/dyld fixup-chains.h.
"""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import json
from pathlib import Path
import plistlib
import struct
import sys
import uuid

from observe_macos26_kernel import ROOT, identify

sys.path.insert(0, str(ROOT / 'UniXNU/kits/NativePrelink'))
from native_prelink import backed_offset, exports

MASK64 = (1 << 64) - 1
ROOTS = ('com.apple.security.AppleImage4', 'com.apple.driver.AppleMobileFileIntegrity')


def macho(data: bytes, at: int = 0) -> dict:
    if at < 0 or at + 32 > len(data):
        raise ValueError('Mach-O header outside BootKC')
    magic, cpu, subtype, kind, count, size = struct.unpack_from('<6I', data, at)
    if magic != 0xfeedfacf or cpu != 0x100000c or subtype & 0xff != 2:
        raise ValueError('requires the matching ARM64E BootKC, not an ordinary ARM64 prelink')
    end = at + 32 + size
    if not 0 < count <= 4096 or end > len(data):
        raise ValueError('BootKC load commands outside file')
    result = dict(kind=kind, subtype=hex(subtype), commands=[], segments=[], entries={}, uuid=None)
    pos = at + 32
    for _ in range(count):
        if pos + 8 > end:
            raise ValueError('truncated load command')
        cmd, length = struct.unpack_from('<II', data, pos)
        if length < 8 or length % 8 or pos + length > end:
            raise ValueError('invalid load command length')
        result['commands'].append((cmd, pos, length))
        if cmd == 0x19:
            if length < 72:
                raise ValueError('truncated segment')
            raw, va, span, off, backed, maximum, initial, nsects, _ = struct.unpack_from('<16s4Q4I', data, pos + 8)
            if length != 72 + 80 * nsects or backed > span or off + backed > len(data) or va + span > 1 << 64:
                raise ValueError('segment outside BootKC')
            seg = dict(name=raw.rstrip(b'\0').decode(), va=va, size=span,
                       fileoff=off, filesize=backed, maxprot=maximum, initprot=initial, sections=[])
            for n in range(nsects):
                name, _, address, extent, offset, align, _, _, flags = struct.unpack_from('<16s16sQQ5I', data, pos + 72 + n * 80)
                if extent and not va <= address < address + extent <= va + span:
                    raise ValueError('section outside segment')
                seg['sections'].append(dict(name=name.rstrip(b'\0').decode(), va=address,
                                             size=extent, fileoff=offset, flags=flags))
            result['segments'].append(seg)
        elif cmd == 0x80000035:
            if length < 32:
                raise ValueError('truncated fileset entry')
            va, offset, nameoff = struct.unpack_from('<QQI', data, pos + 8)
            if not 32 <= nameoff < length:
                raise ValueError('fileset entry name outside command')
            name_end = data.find(b'\0', pos + nameoff, pos + length)
            if name_end < 0:
                raise ValueError('unterminated fileset name')
            name = data[pos + nameoff:name_end].decode()
            if name in result['entries']:
                raise ValueError('duplicate fileset entry')
            result['entries'][name] = (va, offset)
        elif cmd == 0x1b:
            if length != 24 or result['uuid'] is not None:
                raise ValueError('invalid UUID command')
            result['uuid'] = str(uuid.UUID(bytes=data[pos + 8:pos + 24])).upper()
        pos += length
    if pos != end:
        raise ValueError('load command count disagrees with extent')
    return result


def chains(data: bytes, kc: dict):
    commands = [at for cmd, at, length in kc['commands'] if cmd == 0x80000034 and length == 16]
    if len(commands) != 1:
        raise ValueError('requires one BootKC chained-fixups command')
    off, size = struct.unpack_from('<II', data, commands[0] + 8)
    if size < 28 or off + size > len(data):
        raise ValueError('fixups outside BootKC')
    blob = data[off:off + size]
    version, starts, _, _, imports, _, _ = struct.unpack_from('<7I', blob)
    if version or imports or starts + 4 > size:
        raise ValueError('unsupported fixups header or unresolved binds')
    count, = struct.unpack_from('<I', blob, starts)
    if count != len(kc['segments']) or starts + 4 + count * 4 > size:
        raise ValueError('fixup segment table disagrees with BootKC')
    base = min(s['va'] for s in kc['segments'] if s['size'])
    visited = set()
    for index in range(count):
        relative, = struct.unpack_from('<I', blob, starts + 4 + index * 4)
        if not relative:
            continue
        pos = starts + relative
        if pos + 22 > size:
            raise ValueError('chain starts outside fixups')
        span, page_size, fmt, segment, _, pages = struct.unpack_from('<IHHQIH', blob, pos)
        if fmt != 8 or page_size != 16384:
            raise ValueError(f'unsupported BootKC pointer format {fmt} or page size {page_size}')
        if span < 22 + pages * 2 or pos + span > size or base + segment != kc['segments'][index]['va']:
            raise ValueError('chain starts disagree with segment')
        for page in range(pages):
            start, = struct.unpack_from('<H', blob, pos + 22 + page * 2)
            if start == 0xffff:
                continue
            if start & 0x8000:
                raise ValueError('multi-start chain requires a different walker')
            bottom = base + segment + page * page_size
            site = bottom + start
            while True:
                # Format 8 has four-byte stride; a valid eight-byte slot can straddle the page.
                if not bottom <= site < bottom + page_size or site & 3 or site in visited:
                    raise ValueError(f'fixup repeats or crosses page: segment={index} page={page} bottom={bottom:#x} site={site:#x}')
                visited.add(site)
                offset = backed_offset(kc['segments'], site, 8, len(data))
                raw, = struct.unpack_from('<Q', data, offset)
                if (raw >> 30) & 3:
                    raise ValueError('BootKC references another collection')
                target = base + (raw & 0x3fffffff)
                backed_offset(kc['segments'], target, 1, len(data))
                auth = bool(raw >> 63)
                yield dict(site=site, target=target, authenticated=auth,
                           key=(raw >> 49) & 3 if auth else None,
                           diversity=(raw >> 32) & 0xffff if auth else None,
                           address_diversity=bool((raw >> 48) & 1) if auth else None)
                following = (raw >> 51) & 0xfff
                if not following:
                    break
                site += following * 4


def inspect(data: bytes, native_names: dict, roots=ROOTS) -> dict:
    kc = macho(data)
    if kc['kind'] != 12:
        raise ValueError('requires MH_FILESET')
    sections = [s for seg in kc['segments'] for s in seg['sections'] if seg['name'] == '__PRELINK_INFO' and s['name'] == '__info']
    if len(sections) != 1:
        raise ValueError('requires one prelink metadata section')
    section = sections[0]
    off = backed_offset(kc['segments'], section['va'], section['size'], len(data))
    metadata = plistlib.loads(data[off:off + section['size']].split(b'\0', 1)[0])
    entries = {e['CFBundleIdentifier']: e for e in metadata['_PrelinkInfoDictionary']}
    pending, selected, interfaces = list(roots), set(), set()
    while pending:
        name = pending.pop()
        if name in selected or name in interfaces:
            continue
        entry = entries[name]
        if entry.get('OSKernelResource') is True:
            interfaces.add(name)
        else:
            selected.add(name)
            pending.extend(entry.get('OSBundleLibraries', {}))
    modules, ranges, symbol_names = {}, [], defaultdict(list)
    for name, (va, off) in kc['entries'].items():
        image = macho(data, off)
        if image['kind'] != (2 if name == 'com.apple.kernel' else 11):
            raise ValueError('unexpected embedded image type')
        modules[name] = image
        for seg in image['segments']:
            if seg['size'] and seg['name'] != '__LINKEDIT':
                ranges.append((seg['va'], seg['va'] + seg['size'], name))
        if name in selected or name == 'com.apple.kernel':
            for address, names in exports(data, image).items():
                symbol_names[address].extend(names)
    expected = json.loads((ROOT / 'config/macos26.json').read_text())['kernels']['j313ap']['uuid']
    if modules.get('com.apple.kernel', {}).get('uuid') != expected:
        raise ValueError('BootKC does not contain the paired 25F71 M1 kernel')
    ranges.sort()
    for left, right in zip(ranges, ranges[1:]):
        if left[1] > right[0]:
            raise ValueError(f'ambiguous component ownership: {left[2]} / {right[2]}')
    starts = [r[0] for r in ranges]
    def owner(address):
        index = bisect_right(starts, address) - 1
        return ranges[index][2] if index >= 0 and address < ranges[index][1] else None

    reports = {name: dict(uuid=modules[name]['uuid'], dependencies=entries[name].get('OSBundleLibraries', {}),
                         authenticated_fixups=0, fixups=0, pac_keys=Counter(),
                         external_edges=[], initializers=[]) for name in sorted(selected)}
    def edge(name, kind, site, target, extra=None):
        target_owner = owner(target)
        if target_owner == name:
            return
        names = sorted(set(symbol_names.get(target, [])))
        matches = {n: hex(native_names[n]) for n in names if n in native_names} if target_owner == 'com.apple.kernel' else {}
        reports[name]['external_edges'].append(dict(kind=kind, site=hex(site), target=hex(target),
            owner=target_owner, symbols=names, native_symbol_candidates=matches, **(extra or {})))

    for fixup in chains(data, kc):
        name = owner(fixup['site'])
        if name not in selected:
            continue
        reports[name]['fixups'] += 1
        if fixup['authenticated']:
            reports[name]['authenticated_fixups'] += 1
            reports[name]['pac_keys'][('IA', 'IB', 'DA', 'DB')[fixup['key']]] += 1
        edge(name, 'pointer', fixup['site'], fixup['target'], {k: v for k, v in fixup.items() if k not in ('site', 'target')})
    for name in selected:
        for seg in modules[name]['segments']:
            for sec in seg['sections']:
                if sec['name'] in ('__mod_init_func', '__kmod_init', '__init_offsets'):
                    reports[name]['initializers'].append(dict(section=sec['name'], va=hex(sec['va']), size=sec['size']))
            if not seg['initprot'] & 4:
                continue
            for offset in range(seg['fileoff'], seg['fileoff'] + seg['filesize'] - 3, 4):
                word, = struct.unpack_from('<I', data, offset)
                if word & 0x7c000000 != 0x14000000:
                    continue
                immediate = word & 0x3ffffff
                if immediate & (1 << 25):
                    immediate -= 1 << 26
                pc = seg['va'] + offset - seg['fileoff']
                # Linear decoding also sees literal tables embedded in __text.
                # These are candidates for disassembly, never relocation instructions.
                edge(name, 'bl_candidate' if word >> 31 else 'b_candidate', pc,
                     (pc + immediate * 4) & MASK64, {'requires_code_review': True})
    for report in reports.values():
        edges = report['external_edges']
        report['edge_counts'] = dict(Counter(e['kind'] for e in edges))
        imports = [e for e in edges if e['owner'] == 'com.apple.kernel' and e['kind'] == 'pointer']
        report['kernel_pointer_targets'] = len({e['target'] for e in imports})
        report['unresolved_kernel_pointer_targets'] = sorted({e['target'] for e in imports if not e['native_symbol_candidates']})
        report['unresolved_direct_branch_candidates'] = sorted({e['target'] for e in edges
            if e['owner'] == 'com.apple.kernel' and e['kind'] != 'pointer' and not e['native_symbol_candidates']})
        report['undeclared_component_targets'] = sorted({e['owner'] for e in edges if e['owner'] not in selected | {'com.apple.kernel'}} , key=str)
    return dict(bootkc_uuid=kc['uuid'], original_kernel_uuid=expected, roots=list(roots),
                components=reports, kernel_interfaces=sorted(interfaces),
                images_modified=False, loadable=False, original_component_abi_qualified=False,
                branch_scan_limit='linear candidates include literal tables; disassemble before treating them as code',
                next_contracts=['preserve authenticated fixups', 'ARM64/ARM64E callback and C++ ABI',
                                'relocate external instructions and pointers', 'early security initialization before trust_cache_init'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--bootkc', type=Path, default=ROOT / 'private/apple/macos26/kernelcache.release.mac13g.decoded')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    _, native, identity = identify(args.kernel_build.resolve())
    report = inspect(args.bootkc.read_bytes(), native)
    report['native_kernel_uuid'] = identity['uuid']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({name: {key: item[key] for key in ('fixups', 'authenticated_fixups', 'pac_keys',
          'edge_counts', 'kernel_pointer_targets', 'unresolved_kernel_pointer_targets',
          'unresolved_direct_branch_candidates')} for name, item in report['components'].items()}, indent=2))


if __name__ == '__main__':
    main()
