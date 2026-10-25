#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the fixed FAT16 log file and decode its two committed snapshot banks."""
import json
from pathlib import Path
import struct
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / 'config/macoslog.json').read_text())
BLOCK, FILE_BYTES, SLOT_BYTES, SNAPSHOT_BYTES = 4096, 2 << 20, 1 << 20, 82048


def validate_contract(contract: dict) -> None:
    expected = dict(schema='sheng-macoslog-v1', lun=4, block_bytes=BLOCK, disk_blocks=521216,
        partition_index=78, partition_first=448512, partition_blocks=16384,
        partition_name='macoslog', fat_label='MACOSLOG', filename='SHENGLOG.BIN',
        file_bytes=FILE_BYTES, slot_bytes=SLOT_BYTES, snapshot_bytes=SNAPSHOT_BYTES, period_ms=2000,
        partition_uuid='4cd2ed34-2142-4ea4-abf2-ec6c51d117d7',
        partition_type='ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')
    if any(contract.get(key) != value for key, value in expected.items()):
        raise ValueError('macoslog contract differs from the fixed kernel layout')
    if uuid.UUID(contract['file_uuid']).int == 0:
        raise ValueError('macoslog file identity must be nonzero')


validate_contract(CONTRACT)


def contiguous_empty_file(original: bytes, allocated: bytes) -> bytes:
    """Relocate only the newly created empty file into an original free cluster run."""
    cluster, reserved = struct.unpack_from('<BH', original, 13)
    fat_blocks, = struct.unpack_from('<H', original, 22)
    entries, = struct.unpack_from('<H', original, 17)
    if cluster not in (1, 2, 4, 8) or not 0 < fat_blocks <= 32 or not 0 < entries <= 1024 or entries % 128:
        raise ValueError('unsupported original FAT geometry')
    root_first = reserved+2*fat_blocks
    data_first = root_first+entries*32//BLOCK
    clusters = (16384-data_first)//cluster
    count = FILE_BYTES//(cluster*BLOCK)
    start, length = 0, 0
    old_fat = original[reserved*BLOCK:(reserved+fat_blocks)*BLOCK]
    fat = allocated[reserved*BLOCK:(reserved+fat_blocks)*BLOCK]
    if (len(old_fat) != fat_blocks*BLOCK or (clusters+2)*2 > len(old_fat)
            or old_fat != original[(reserved+fat_blocks)*BLOCK:(reserved+2*fat_blocks)*BLOCK]
            or fat != allocated[(reserved+fat_blocks)*BLOCK:(reserved+2*fat_blocks)*BLOCK]):
        raise ValueError('original or allocated FAT copies differ')
    for i in range(2, clusters+2):
        length = length+1 if old_fat[i*2:i*2+2] == bytes(2) else 0
        if length == count:
            start = i+1-count
            break
    if not start:
        raise ValueError('no contiguous original free extent fits the log file')
    targets = []
    for at in range(root_first*BLOCK, data_first*BLOCK, 32):
        if allocated[at] == 0:
            break
        if allocated[at:at+11] == b'SHENGLOGBIN' and allocated[at+11] != 0x0f:
            targets.append(at)
    if len(targets) != 1:
        raise ValueError('requires exactly one newly allocated log file')
    entry = targets[0]
    current, = struct.unpack_from('<H', allocated, entry+26)
    visited = set()
    for _ in range(count):
        if (current < 2 or current >= clusters+2 or current in visited
                or old_fat[current*2:current*2+2] != bytes(2)):
            raise ValueError('new file allocation intersects existing clusters')
        visited.add(current)
        current, = struct.unpack_from('<H', fat, current*2)
    if current < 0xfff8:
        raise ValueError('new file allocation length differs')
    for i in range(len(old_fat)//2):
        if i not in visited and fat[i*2:i*2+2] != old_fat[i*2:i*2+2]:
            raise ValueError('allocator modified another FAT entry')
    rewritten = bytearray(old_fat)
    for i in range(count):
        struct.pack_into('<H', rewritten, (start+i)*2, 0xffff if i+1 == count else start+i+1)
    result = bytearray(allocated)
    for copy in range(2):
        at = (reserved+copy*fat_blocks)*BLOCK
        result[at:at+len(rewritten)] = rewritten
    struct.pack_into('<H', result, entry+26, start)
    offset = (data_first+(start-2)*cluster)*BLOCK
    result[offset:offset+FILE_BYTES] = bytes(FILE_BYTES)
    return bytes(result)


def preserve_allocations(before: bytes, after: bytes) -> None:
    """Reject a candidate that changes existing entries, FAT chains or allocated data."""
    if len(before) != 64 << 20 or len(after) != len(before):
        raise ValueError('unexpected partition size')
    cluster, reserved = struct.unpack_from('<BH', before, 13)
    fat_blocks, = struct.unpack_from('<H', before, 22)
    entries, = struct.unpack_from('<H', before, 17)
    if cluster not in (1, 2, 4, 8) or not 0 < reserved < 16384 or not 0 < fat_blocks <= 32 or not 0 < entries <= 1024 or entries % 128:
        raise ValueError('original FAT geometry differs')
    if before[:reserved*BLOCK] != after[:reserved*BLOCK]:
        raise ValueError('candidate changed original FAT boot/reserved blocks')
    root_first, root_bytes = reserved+2*fat_blocks, entries*32
    data_first = root_first+root_bytes//BLOCK
    clusters = (16384-data_first)//cluster
    if not 4085 <= clusters < 65525 or (clusters+2)*2 > fat_blocks*BLOCK:
        raise ValueError('original FAT data extent differs')
    fat = before[reserved*BLOCK:(reserved+fat_blocks)*BLOCK]
    if fat != before[(reserved+fat_blocks)*BLOCK:(reserved+2*fat_blocks)*BLOCK]:
        raise ValueError('original FAT copies differ')
    for index in range(2, clusters+2):
        old = fat[index*2:index*2+2]
        if old == bytes(2):
            continue
        for copy in range(2):
            at = (reserved+copy*fat_blocks)*BLOCK+index*2
            if after[at:at+2] != old:
                raise ValueError('candidate changed an existing FAT chain')
        at = (data_first+(index-2)*cluster)*BLOCK
        size = cluster*BLOCK
        if before[at:at+size] != after[at:at+size]:
            raise ValueError('candidate changed existing allocated file/directory data')
    for at in range(root_first*BLOCK, root_first*BLOCK+root_bytes, 32):
        if before[at] == 0:
            break
        if before[at] != 0xe5 and before[at:at+32] != after[at:at+32]:
            raise ValueError('candidate changed an existing root entry')


def locate(image: bytes) -> int:
    if len(image) != 64 << 20:
        raise ValueError('requires the complete macoslog FAT16 image')
    sector, cluster, reserved, fats, entries, sectors, _, fat_blocks = struct.unpack_from('<HBHBHHBH', image, 11)
    if (sector != BLOCK or fats != 2 or sectors != 16384 or struct.unpack_from('<I', image, 32)[0]
            or image[43:54] != b'MACOSLOG   ' or image[54:62] != b'FAT16   '
            or image[510:512] != b'\x55\xaa' or not reserved or not 0 < fat_blocks <= 32
            or not 0 < entries <= 1024 or entries % 128 or cluster not in (1, 2, 4, 8)):
        raise ValueError('unexpected FAT16 geometry')
    root_first, root_bytes = reserved + fats * fat_blocks, entries * 32
    data_first = root_first + root_bytes // BLOCK
    clusters = (sectors - data_first) // cluster
    if not 4085 <= clusters < 65525 or (clusters + 2) * 2 > fat_blocks * BLOCK:
        raise ValueError('invalid FAT16 cluster count')
    fat = image[reserved*BLOCK:(reserved+fat_blocks)*BLOCK]
    if fat != image[(reserved+fat_blocks)*BLOCK:(reserved+2*fat_blocks)*BLOCK]:
        raise ValueError('FAT copies differ')
    root = image[root_first*BLOCK:root_first*BLOCK+root_bytes]
    all_entries = []
    for at in range(0, len(root), 32):
        entry = root[at:at+32]
        if entry[0] == 0:
            break
        if entry[0] != 0xe5 and entry[11] != 0x0f:
            all_entries.append(entry)
    found = [e for e in all_entries if e[:11] == b'SHENGLOGBIN']
    if (len(found) != 1 or found[0][11] & 0x19 or struct.unpack_from('<H', found[0], 20)[0]
            or struct.unpack_from('<I', found[0], 28)[0] != FILE_BYTES):
        raise ValueError('requires one writable fixed-size SHENGLOG.BIN')
    start = struct.unpack_from('<H', found[0], 26)[0]
    count = FILE_BYTES // (BLOCK * cluster)
    if start < 2 or start + count > clusters + 2:
        raise ValueError('file outside FAT data region')
    for i in range(count):
        next_ = struct.unpack_from('<H', fat, (start+i)*2)[0]
        invalid = next_ < 0xfff8 if i + 1 == count else next_ != start+i+1
        if invalid:
            raise ValueError('log file is fragmented or truncated')
    for i in range(2, clusters+2):
        next_ = struct.unpack_from('<H', fat, i*2)[0]
        if start <= next_ < start+count and (next_ == start or i != next_-1):
            raise ValueError('log file has a cross-linked FAT chain')
    for entry in all_entries:
        if entry[:11] != b'SHENGLOGBIN' and start <= struct.unpack_from('<H', entry, 26)[0] < start+count:
            raise ValueError('another entry shares log clusters')
    offset = (data_first + (start-2)*cluster)*BLOCK
    if offset + FILE_BYTES > len(image):
        raise ValueError('log extent exceeds partition')
    return offset


def guard(first_lba: int) -> bytes:
    data = bytearray(BLOCK)
    struct.pack_into('<8sII16s16sQQQ', data, 0, b'SHNGSLOT', 1, BLOCK,
        uuid.UUID(CONTRACT['file_uuid']).bytes, uuid.UUID(CONTRACT['partition_uuid']).bytes_le,
        first_lba, FILE_BYTES//BLOCK, SNAPSHOT_BYTES)
    struct.pack_into('<I', data, 4092, zlib.crc32(data[:4092]))
    return bytes(data)


def decode(data: bytes, expected_uuid: str) -> tuple[bytes, dict]:
    from decode_native_log import decode as decode_snapshot
    if len(data) != FILE_BYTES:
        raise ValueError('fixed log file is truncated')
    marker = data[-BLOCK:]
    first = struct.unpack_from('<Q', marker, 48)[0]
    if (not CONTRACT['partition_first'] < first <= CONTRACT['partition_first'] + CONTRACT['partition_blocks'] - FILE_BYTES//BLOCK
            or marker != guard(first)):
        raise ValueError('fixed log file ownership guard differs')
    snapshots, errors = [], []
    for bank in range(2):
        at = bank*SLOT_BYTES
        h = data[at:at+BLOCK]
        generation = struct.unpack_from('<Q', h, 16)[0]
        if (h[:8] != b'SHNCAP01' or struct.unpack_from('<II', h, 8) != (1, BLOCK)
                or not 0 < generation < (1 << 64)-1 or struct.unpack_from('<I', h, 24)[0] != SNAPSHOT_BYTES
                or h[64:80] != uuid.UUID(CONTRACT['file_uuid']).bytes
                or struct.unpack_from('<I', h, 4092)[0] != zlib.crc32(h[:4092])):
            errors.append(dict(bank=bank, reason='uncommitted or invalid header'))
            continue
        raw = data[at+BLOCK:at+BLOCK+SNAPSHOT_BYTES]
        if (struct.unpack_from('<I', h, 28)[0] != zlib.crc32(raw) or h[32:48] != raw[112:128]
                or h[48:64] != raw[24:40]):
            errors.append(dict(bank=bank, reason='payload or metadata mismatch'))
            continue
        identity = str(uuid.UUID(bytes=h[32:48])).upper()
        if identity != expected_uuid.upper():
            errors.append(dict(bank=bank, reason='different kernel UUID', uuid=identity))
            continue
        try:
            text, report = decode_snapshot(raw, expected_uuid)
        except ValueError as error:
            errors.append(dict(bank=bank, reason=str(error)))
            continue
        snapshots.append((generation, bank, raw, text, report))
    if not snapshots:
        raise ValueError('no committed snapshot for the selected kernel: '+json.dumps(errors))
    generation, bank, raw, text, report = max(snapshots, key=lambda row: row[0])
    report.update(generation=generation, bank=bank, rejected_banks=errors,
                  snapshot_period_ms=CONTRACT['period_ms'], latest_panic_guaranteed=False,
                  streaming_full_history=False, filesystem_metadata_written_by_kernel=False)
    return raw, dict(console_text=text.decode(errors='replace'), **report)
