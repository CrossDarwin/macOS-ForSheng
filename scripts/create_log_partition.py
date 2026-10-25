#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Plan or create macoslog only in the verified free tail of sheng UFS LUN sde."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess
import uuid
import zlib

from backup_device import parse_gpt

ROOT = Path(__file__).resolve().parents[1]
BLOCK = 4096
WINDOW = 1048576
LENGTH = 64 * 1048576
NAME = 'macoslog'
BASIC_DATA = uuid.UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Recovery:
    def __init__(self, serial):
        self.adb = ['adb', '-s', serial]
        state = subprocess.check_output(self.adb + ['get-state'], text=True, timeout=10).strip()
        if state != 'recovery' or self.shell('id -u') != '0' or self.shell('getprop ro.product.device') != 'sheng':
            raise ValueError('requires root ADB in sheng recovery')
        if int(self.shell('cat /sys/block/sde/queue/logical_block_size')) != BLOCK:
            raise ValueError('unexpected logical block size')
        self.lbas = int(self.shell('cat /sys/block/sde/size')) * 512 // BLOCK

    def shell(self, command):
        return subprocess.check_output(self.adb + ['shell', command], text=True, timeout=30).strip()

    def read(self, start, count):
        data = subprocess.check_output(self.adb + ['exec-out', 'sh', '-c',
            f'dd if=/dev/block/sde bs={BLOCK} skip={start} count={count} 2>/dev/null'], timeout=120)
        if len(data) != count * BLOCK:
            raise ValueError('incomplete sde read')
        return data

    def write(self, path, start, count):
        if path.stat().st_size != count * BLOCK:
            raise ValueError('unexpected write extent')
        remote = '/tmp/macoslog-' + path.name
        subprocess.run(self.adb + ['push', str(path), remote], check=True, timeout=120,
                       stdout=subprocess.DEVNULL)
        try:
            self.shell(f'dd if={shlex.quote(remote)} of=/dev/block/sde bs={BLOCK} seek={start} count={count} conv=notrunc && sync')
            if self.read(start, count) != path.read_bytes():
                raise ValueError('sde write readback differs')
        finally:
            self.shell('rm -f ' + shlex.quote(remote))


def geometry(data, lbas, start):
    result = parse_gpt(data, BLOCK, lbas, start)
    at = (1 if start == 0 else lbas - 1) - start
    header = data[at * BLOCK:(at + 1) * BLOCK]
    entries_lba, count, stride, _ = struct.unpack_from('<QIII', header, 72)
    begin = (entries_lba - start) * BLOCK
    entries = data[begin:begin + count * stride]
    return result, header, entries, entries_lba, count, stride


def update(data, lbas, start, slot, entry):
    _, header, entries, entries_lba, count, stride = geometry(data, lbas, start)
    array = bytearray(entries)
    array[slot * stride:(slot + 1) * stride] = entry
    header = bytearray(header)
    struct.pack_into('<I', header, 88, zlib.crc32(array))
    struct.pack_into('<I', header, 16, 0)
    size = struct.unpack_from('<I', header, 12)[0]
    struct.pack_into('<I', header, 16, zlib.crc32(header[:size]))
    result = bytearray(data)
    at = ((1 if start == 0 else lbas - 1) - start) * BLOCK
    result[at:at + BLOCK] = header
    begin = (entries_lba - start) * BLOCK
    result[begin:begin + len(array)] = array
    parse_gpt(result, BLOCK, lbas, start)
    return bytes(result)


def prepare(device, directory):
    if directory.exists():
        raise ValueError('choose a new backup directory; existing rollback material is preserved')
    old = json.loads((ROOT / 'private/backups/20261023-gpt-boot/manifest.json').read_text())['gpt']['sde']
    if device.lbas != old['device_lbas']:
        raise ValueError('current sde capacity differs from baseline')
    directory.mkdir(parents=True, mode=0o700)
    current = {}
    for kind, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        raw = device.read(start, WINDOW // BLOCK)
        baseline = (ROOT / 'private/backups/20261023-gpt-boot' / old['copies'][kind]['file']).read_bytes()
        now = geometry(raw, device.lbas, start)
        before = geometry(baseline, device.lbas, start)
        if now[0] != before[0] or now[1][56:72] != before[1][56:72] or now[4:] != before[4:]:
            raise ValueError('current partition geometry or identity differs from baseline')
        # ABL updates boot-slot attributes; accept attribute changes only for these two entries and preserve their current values.
        for i in range(now[4]):
            a = now[2][i * now[5]:(i + 1) * now[5]]
            b = before[2][i * now[5]:(i + 1) * now[5]]
            name = a[56:128].decode('utf-16-le').split('\0', 1)[0]
            if a != b and not (name in ('boot_a', 'boot_b') and a[:48] + a[56:] == b[:48] + b[56:]):
                raise ValueError('current GPT entry changed beyond boot slot attributes')
        (directory / f'before-{kind}.bin').write_bytes(raw)
        current[kind] = raw
    g, header, entries, _, count, stride = geometry(current['primary'], device.lbas, 0)
    other = geometry(current['secondary'], device.lbas, device.lbas - WINDOW // BLOCK)
    if entries != other[2] or header[56:72] != other[1][56:72]:
        raise ValueError('GPT copies disagree')
    if any(p['name'] == NAME for p in g['partitions']):
        raise ValueError('macoslog already exists')
    first = (max(p['last_lba'] for p in g['partitions']) + 256) // 256 * 256
    last = first + LENGTH // BLOCK - 1
    if last > g['last_usable']:
        raise ValueError('no 64 MiB aligned free tail; userdata will not be resized')
    slot = next((i for i in range(count) if entries[i * stride:(i + 1) * stride] == bytes(stride)), None)
    if slot is None:
        raise ValueError('no entirely empty GPT entry')
    unique = uuid.uuid4()
    entry = bytearray(stride)
    entry[:16], entry[16:32] = BASIC_DATA.bytes_le, unique.bytes_le
    struct.pack_into('<QQQ', entry, 32, first, last, 0)
    name = NAME.encode('utf-16-le')
    entry[56:56 + len(name)] = name
    for kind, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        result = update(current[kind], device.lbas, start, slot, entry)
        after = parse_gpt(result, BLOCK, device.lbas, start)
        if after['partitions'] != g['partitions'] + [dict(name=NAME, first_lba=first, last_lba=last)]:
            raise ValueError('existing GPT entries changed')
        (directory / f'after-{kind}.bin').write_bytes(result)
    image = directory / 'macoslog-fat16.img'
    with image.open('xb') as stream:
        stream.truncate(LENGTH)
    subprocess.run(['mkfs.fat', '-F', '16', '-S', str(BLOCK), '-s', '1', '-n', 'MACOSLOG', str(image)], check=True)
    record = dict(serial=device.adb[2], disk='sde', disk_lbas=device.lbas, logical_block_bytes=BLOCK,
                  entry_index=slot + 1, name=NAME, unique_guid=str(unique), type_guid=str(BASIC_DATA),
                  first_lba=first, last_lba=last, bytes=LENGTH, filesystem='FAT16', label='MACOSLOG',
                  existing_partitions_changed=False, userdata_resized=False, applied=False,
                  before={k:digest(v) for k,v in current.items()})
    (directory / 'plan.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def apply(device, directory):
    record = json.loads((directory / 'plan.json').read_text())
    if (record['applied'] or record['serial'] != device.adb[2] or record['disk_lbas'] != device.lbas
            or record['bytes'] != LENGTH or record['disk'] != 'sde'):
        raise ValueError('stale or mismatched plan')
    for kind, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        raw = device.read(start, WINDOW // BLOCK)
        if digest(raw) != record['before'][kind] or raw != (directory / f'before-{kind}.bin').read_bytes():
            raise ValueError('GPT changed since preparation')
        g = parse_gpt(raw, BLOCK, device.lbas, start)
        if any(max(p['first_lba'],record['first_lba']) <= min(p['last_lba'],record['last_lba']) for p in g['partitions']):
            raise ValueError('planned partition overlaps a current partition')
    # Save the currently unused extent before writing so this operation remains recoverable.
    free = directory / 'before-free-tail.bin'
    if free.exists():
        raise ValueError('previous apply attempt exists; inspect before retrying')
    free.write_bytes(device.read(record['first_lba'], LENGTH // BLOCK))
    for kind, window_start in (('secondary', device.lbas - WINDOW // BLOCK), ('primary', 0)):
        data = (directory / f'after-{kind}.bin').read_bytes()
        _, header, entries, start, _, _ = geometry(data, device.lbas, window_start)
        count = (len(entries) + BLOCK - 1) // BLOCK
        payload = data[(start - window_start) * BLOCK:(start - window_start + count) * BLOCK]
        path = directory / f'write-{kind}-array.bin'; path.write_bytes(payload)
        device.write(path, start, count)
        path = directory / f'write-{kind}-header.bin'; path.write_bytes(header)
        device.write(path, 1 if kind == 'primary' else device.lbas - 1, 1)
    device.write(directory / 'macoslog-fat16.img', record['first_lba'], LENGTH // BLOCK)
    for kind, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        raw = device.read(start, WINDOW // BLOCK)
        if raw != (directory / f'after-{kind}.bin').read_bytes():
            raise ValueError('final GPT readback differs')
        (directory / f'verified-{kind}.bin').write_bytes(raw)
    record.update(applied=True, readback_verified=True, rollback_free_tail_sha256=digest(free.read_bytes()),
                  filesystem_image_sha256=digest((directory / 'macoslog-fat16.img').read_bytes()))
    (directory / 'plan.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='apply a previously prepared, unchanged free-tail plan')
    args = parser.parse_args()
    device = Recovery(args.serial)
    result = apply(device,args.output) if args.apply else prepare(device,args.output)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
