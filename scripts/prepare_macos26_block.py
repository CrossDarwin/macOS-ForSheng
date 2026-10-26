#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Expand the paired Copy/Zero UDIF recovery disk for read-only QEMU block I/O."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]


def expand(source: Path, output: Path, verification: dict) -> dict:
    if source.name != verification['source_dmg'] or verification['ipsw_build'] != '25F71':
        raise ValueError('requires the paired 25F71 recovery image')
    if output.exists():
        raise ValueError('output exists; reuse its recorded conversion or select another path')
    with source.open('rb') as f:
        f.seek(-512, 2)
        trailer = f.read(512)
        if trailer[:4] != b'koly':
            raise ValueError('missing UDIF trailer')
        fork, fork_size = struct.unpack_from('>QQ', trailer, 24)
        xml_at, xml_size = struct.unpack_from('>QQ', trailer, 216)
        sectors, = struct.unpack_from('>Q', trailer, 492)
        if not 0 < sectors * 512 <= 4 << 30 or xml_size > 16 << 20 or fork + fork_size > xml_at:
            raise ValueError('unexpected paired UDIF bounds')
        f.seek(xml_at)
        entries = plistlib.loads(f.read(xml_size))['resource-fork']['blkx']
        entries.sort(key=lambda e: struct.unpack_from('>Q', e['Data'], 8)[0])
        output.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        tables, cursor = [], 0
        try:
            with output.open('xb') as dest:
                dest.truncate(sectors * 512)
                for entry in entries:
                    b = entry['Data']
                    start, count, data_offset = struct.unpack_from('>QQQ', b, 8)
                    ctype, cbits, expected_crc = struct.unpack_from('>III', b, 64)
                    runs, = struct.unpack_from('>I', b, 200)
                    if (b[:4] != b'mish' or start != cursor or ctype != 2 or cbits != 32
                            or len(b) != 204 + runs * 40 or start + count > sectors):
                        raise ValueError('unexpected paired block table')
                    done, crc, terminated = 0, 0, False
                    for i in range(runs):
                        kind, _, sector, extent, offset, packed = struct.unpack_from('>II4Q', b, 204 + i * 40)
                        if kind == 0xffffffff:
                            if i != runs - 1 or extent or sector != count:
                                raise ValueError('invalid UDIF run terminator')
                            terminated = True
                            continue
                        if (kind not in (1, 2) or sector != done or done + extent > count
                                or (kind == 1 and packed != extent * 512)
                                or (kind == 2 and packed)):
                            raise ValueError('only actual contiguous Copy/Zero runs are supported')
                        if kind == 1:
                            if data_offset + offset + packed > fork_size:
                                raise ValueError('copy run exceeds source data fork')
                            f.seek(fork + data_offset + offset)
                        dest.seek((start + sector) * 512)
                        remaining = extent * 512
                        while remaining:
                            size = min(1 << 20, remaining)
                            chunk = f.read(size) if kind == 1 else bytes(size)
                            if len(chunk) != size:
                                raise ValueError('short UDIF copy run')
                            if kind == 1:
                                dest.write(chunk)
                                # UDIF Zero2 holes are excluded from the table CRC
                                crc = zlib.crc32(chunk, crc)
                            digest.update(chunk)
                            remaining -= size
                        done += extent
                    if not terminated or done != count or crc != expected_crc:
                        raise ValueError(f'UDIF table CRC mismatch: {entry["Name"]}')
                    tables.append(dict(name=entry['Name'], first_sector=start, sectors=count, crc32=hex(crc)))
                    cursor += count
            if cursor != sectors:
                raise ValueError('UDIF tables do not cover the complete disk')
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    with output.open('rb') as f:
        first = f.read(512)
        header = bytearray(f.read(512))
    if first[-2:] != b'\x55\xaa' or header[:8] != b'EFI PART':
        raise ValueError('reconstructed disk lacks its actual MBR and GPT')
    size, expected = struct.unpack_from('<II', header, 12)
    struct.pack_into('<I', header, 16, 0)
    if not 92 <= size <= 512 or zlib.crc32(header[:size]) != expected:
        raise ValueError('actual GPT header checksum mismatch')
    return dict(build='25F71', source=source.name, source_dmg_sha256=verification['dmg_sha256'],
                bytes=sectors * 512, sha256=digest.hexdigest(), tables=tables,
                first_sector_sha256=hashlib.sha256(first).hexdigest(), read_only_qemu_input=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verification = json.loads((ROOT / 'private/apple/macos26/recovery-check/verification.json').read_text())
    result = expand(ROOT / 'private/apple/macos26' / verification['source_dmg'], args.output, verification)
    args.output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
