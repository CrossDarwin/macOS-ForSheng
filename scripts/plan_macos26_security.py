#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Plan native ARM64E security-module relocation without emitting a boot image."""
import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

from inspect_macos26_security import ROOT, ROOTS, chains, exports, inspect, macho
from observe_macos26_kernel import identify

PAGE = 16384
MASK64 = (1 << 64) - 1
SHA256_WORDS = '74ef7306e7452d6859b6463ce496b8df30925f69e1b2969e1f3f34bbc9c6af04'
# 原版汇编把查表数据放在__text中，必须按实际UUID与完整字节区分
COMPRESSION_UUID = 'EE081FA4-270B-3359-9DFD-61B9D6DBFAB1'
COMPRESSION_LITERALS = (
    (0xec0, 528, 'f7bb30778915b574b63a17573babfdeb97251ae92fb57e7302e69783f454f92a',
     'LZ4 SIMD shuffle and advance tables'),
    (0x6060, 40, '48bdf8e57f8647f2ef3cfda5b500209c4be9b5742632db0ff3614aca8d7ee63d',
     'Adler32 vector weights and reduction constants'),
)



def relative(word: int, pc: int):
    def signed(value, bits):
        return value - (1 << bits) if value & (1 << (bits - 1)) else value
    if word & 0x9f000000 in (0x10000000, 0x90000000):
        offset = signed(((word >> 5) & 0x7ffff) << 2 | ((word >> 29) & 3), 21)
        page = bool(word & 0x80000000)
        return ('adrp' if page else 'adr',
                (((pc & ~4095) + (offset << 12)) if page else pc + offset) & MASK64)
    if word & 0x7c000000 == 0x14000000:
        return ('bl' if word >> 31 else 'b', (pc + (signed(word & 0x3ffffff, 26) << 2)) & MASK64)
    if word & 0xff000010 == 0x54000000 or word & 0x7e000000 == 0x34000000 or word & 0x3b000000 == 0x18000000:
        return ('relative19', (pc + (signed((word >> 5) & 0x7ffff, 19) << 2)) & MASK64)
    if word & 0x7e000000 == 0x36000000:
        return ('relative14', (pc + (signed((word >> 5) & 0x3fff, 14) << 2)) & MASK64)
    return None


def plan(data: bytes, native: dict, identity: dict, slide: int, roots=ROOTS) -> dict:
    if slide <= 0 or slide % PAGE:
        raise ValueError('module slide must be positive and 16 KiB aligned')
    report = inspect(data, native, roots)
    selected = set(report['components'])
    kc = macho(data)
    modules = {name: macho(data, offset) for name, (_, offset) in kc['entries'].items()}
    ranges = sorted((seg['va'], seg['va'] + seg['size'], name)
                    for name, module in modules.items() for seg in module['segments']
                    if seg['size'] and seg['name'] != '__LINKEDIT')
    starts = [r[0] for r in ranges]

    def owner(address):
        index = bisect_right(starts, address) - 1
        return ranges[index][2] if index >= 0 and address < ranges[index][1] else None

    selected_ranges = [(lo, hi) for lo, hi, name in ranges if name in selected]
    for lo, hi in selected_ranges:
        if hi + slide > MASK64:
            raise ValueError('module placement overflows the address space')
        # The emitter will map whole pages, including holes between modules.
        bottom, top = (lo + slide) & -PAGE, (hi + slide + PAGE - 1) & -PAGE
        if any(s['size'] and bottom < s['va'] + s['size'] and s['va'] < top
               for s in identity['segments']):
            raise ValueError('module placement overlaps the native kernel')
        if top - 0xfffffe0007004000 > 0x20000000:
            raise ValueError('module placement exceeds the owned 512 MiB window')

    old_exports = exports(data, modules['com.apple.kernel'])

    def resolve(target):
        belonging = owner(target)
        if belonging in selected:
            return target + slide
        if belonging != 'com.apple.kernel':
            raise ValueError(f'undeclared import {target:#x}: {belonging}')
        names = old_exports.get(target, [])
        addresses = {native[name] for name in names if name in native}
        if len(addresses) != 1:
            raise ValueError(f'ambiguous or missing native import {target:#x}: {names}')
        return addresses.pop()

    pointers = []
    for item in chains(data, kc):
        if owner(item['site']) not in selected:
            continue
        new_target = resolve(item['target'])
        if not 0 <= new_target - 0xfffffe0007004000 <= 0xffffffff:
            raise ValueError('relocated pointer does not fit an authenticated format-7 target')
        pointers.append(dict(item, new_site=item['site'] + slide, new_target=new_target))

    patches, preserved, literals, blockers = [], Counter(), [], []
    for name in sorted(selected):
        for seg in modules[name]['segments']:
            if not seg['initprot'] & 4:
                continue
            blob = data[seg['fileoff']:seg['fileoff'] + seg['filesize']]
            excluded = set()
            if (name == 'com.apple.AppleFSCompression.AppleFSCompressionTypeZlib'
                    and modules[name]['uuid'] == COMPRESSION_UUID and seg['name'] == '__TEXT_EXEC'):
                for offset, size, digest, purpose in COMPRESSION_LITERALS:
                    literal = blob[offset:offset + size]
                    if (hashlib.sha256(literal).hexdigest() != digest
                            or blob[offset + size:offset + size + 4] != bytes.fromhex('5f2403d5')):
                        raise ValueError('paired compression inline table changed')
                    excluded.update(range(offset, offset + size, 4))
                    literals.append(dict(module=name, va=seg['va'] + offset,
                                         bytes=size, sha256=digest, purpose=purpose))
            position = 0
            while (position := blob.find(bytes.fromhex('982f8a42'), position)) >= 0:
                literal = blob[position:position + 256]
                if position % 4 == 0 and hashlib.sha256(literal).hexdigest() == SHA256_WORDS:
                    excluded.update(range(position, position + 256, 4))
                    literals.append(dict(module=name, va=seg['va'] + position,
                                         bytes=256, sha256=SHA256_WORDS))
                position += 4
            for off in range(0, len(blob) - 3, 4):
                if off in excluded:
                    continue
                word, = struct.unpack_from('<I', blob, off)
                pc = seg['va'] + off
                decoded = relative(word, pc)
                if decoded is None:
                    continue
                kind, target = decoded
                # ADRP names a 4 KiB page. Its first byte can belong to a
                # neighbouring module; only the later offset picks the object.
                internal = (any(lo < target + 4096 and target < hi for lo, hi in selected_ranges)
                            if kind == 'adrp' else owner(target) in selected)
                if internal:
                    preserved[kind] += 1
                    continue
                if kind not in ('b', 'bl'):
                    blockers.append(dict(module=name, site=pc, word=word, kind=kind,
                                         target=target, reason='requires instruction dataflow review'))
                    continue
                try:
                    new_target = resolve(target)
                    delta = new_target - (pc + slide)
                    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
                        raise ValueError('branch requires an out-of-range trampoline')
                except ValueError as error:
                    blockers.append(dict(module=name, site=pc, word=word, kind=kind,
                                         target=target, reason=str(error)))
                    continue
                replacement = (word & 0xfc000000) | ((delta >> 2) & 0x3ffffff)
                if relative(replacement, pc + slide) != (kind, new_target):
                    raise ValueError('relocated branch failed its decode check')
                patches.append(dict(module=name, site=pc, new_site=pc + slide, word=word,
                                    replacement=replacement, target=target, new_target=new_target,
                                    symbols=old_exports.get(target, [])))

    return dict(plan_version=1, roots=report['roots'], native_kernel_uuid=identity['uuid'], kernel_sha256=identity['kernel_sha256'],
                bootkc_sha256=hashlib.sha256(data).hexdigest(), module_slide=slide,
                modules={name: dict(uuid=modules[name]['uuid'],
                    dependencies=report['components'][name]['dependencies'],
                    header_va=kc['entries'][name][0] + slide,
                    segments=[dict(s, va=s['va'] + slide) for s in modules[name]['segments']
                              if s['size'] and s['name'] != '__LINKEDIT']) for name in sorted(selected)},
                pointer_relocations=pointers, branch_relocations=patches,
                kernel_interfaces=report['kernel_interfaces'],
                preserved_relative_encodings=dict(preserved), excluded_literals=literals,
                instruction_blockers=blockers, authenticated_pointers=sum(p['authenticated'] for p in pointers),
                register_dataflow_qualified=False,
                images_modified=False, loadable=False, original_component_abi_qualified=False,
                pending=['emit coalesced mappings and rebuilt format-7 chains',
                         'rebase embedded headers and prelink metadata',
                         'run real constructors and security registration before MAC lockdown',
                         'validate callback, kalloc and C++ ABI in QEMU'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--bootkc', type=Path,
                        default=ROOT / 'private/apple/macos26/kernelcache.release.mac13g.decoded')
    parser.add_argument('--slide', type=lambda value: int(value, 0), default=0x2000000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        _, native, identity = identify(args.kernel_build.resolve())
        result = plan(args.bootkc.read_bytes(), native, identity, args.slide)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(dict(pointers=len(result['pointer_relocations']),
        authenticated_pointers=result['authenticated_pointers'],
        branches=len(result['branch_relocations']),
        instruction_blockers=len(result['instruction_blockers']),
        loadable=result['loadable']), indent=2))
    if result['instruction_blockers']:
        parser.exit(1, f'instruction blockers retained in {args.output}\n')


if __name__ == '__main__':
    main()
