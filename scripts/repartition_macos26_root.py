#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rebuild sheng userdata and reserve an explicitly authorized macosroot extent."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess
import uuid

from backup_device import parse_gpt
from create_log_partition import geometry, update

ROOT = Path(__file__).resolve().parents[1]
BLOCK = 4096
WINDOW = 1 << 20
BASIC_DATA = uuid.UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def layout(primary, secondary, lbas, macos_gib):
    if macos_gib not in (32, 64):
        raise ValueError('choose the explicit 32 or 64 GiB root allocation')
    before, header, entries, _, count, stride = geometry(primary, lbas, 0)
    other = geometry(secondary, lbas, lbas - WINDOW // BLOCK)
    if (entries != other[2] or header[56:72] != other[1][56:72]
            or before['partitions'] != other[0]['partitions']):
        raise ValueError('primary and secondary GPT copies disagree')
    occupied = [(i, entries[i * stride:(i + 1) * stride]) for i in range(count)
                if entries[i * stride:i * stride + 16] != bytes(16)]
    userdata = [(i, entry) for i, entry in occupied
                if entry[56:128].decode('utf-16-le').split('\0')[0] == 'userdata']
    if len(userdata) != 1 or any(p['name'] == 'macosroot' for p in before['partitions']):
        raise ValueError('requires exactly one userdata and no existing macosroot')
    index, entry = userdata[0]
    first, last = struct.unpack_from('<QQ', entry, 32)
    if index != 28 or last != before['last_usable'] or any(
            struct.unpack_from('<Q', e, 40)[0] >= first for i, e in occupied if i != index):
        raise ValueError('requires the verified final sda29 userdata geometry')
    # Allocate only from the authorized disposable userdata tail; preserve every other GPT entry byte for byte.
    root_end = (last + 1) // (WINDOW // BLOCK) * (WINDOW // BLOCK)
    root_first = root_end - macos_gib * (1 << 30) // BLOCK
    if root_first - first < 16 * (1 << 30) // BLOCK:
        raise ValueError('remaining Android userdata would be smaller than 16 GiB')
    slot = next((i for i in range(count) if entries[i * stride:(i + 1) * stride] == bytes(stride)), None)
    if slot is None:
        raise ValueError('no completely empty GPT entry')
    android = bytearray(entry)
    struct.pack_into('<Q', android, 40, root_first - 1)
    root = bytearray(stride)
    identity = uuid.uuid4()
    root[:16], root[16:32] = BASIC_DATA.bytes_le, identity.bytes_le
    struct.pack_into('<QQQ', root, 32, root_first, root_end - 1, 0)
    root[56:74] = 'macosroot'.encode('utf-16-le')
    outputs = {}
    for name, raw, start in (('primary', primary, 0), ('secondary', secondary, lbas - WINDOW // BLOCK)):
        resized = update(raw, lbas, start, index, android)
        changed = update(resized, lbas, start, slot, root)
        after = geometry(changed, lbas, start)
        for i in range(count):
            expected = bytes(android) if i == index else bytes(root) if i == slot else entries[i * stride:(i + 1) * stride]
            if after[2][i * stride:(i + 1) * stride] != expected:
                raise ValueError('unexpected GPT entry change')
        outputs[name] = changed
    return outputs, dict(disk='sda', disk_lbas=lbas, logical_block_bytes=BLOCK,
        disk_guid=str(uuid.UUID(bytes_le=header[56:72])), userdata_index=index + 1,
        userdata_first_lba=first, userdata_last_lba=root_first - 1,
        userdata_bytes=(root_first - first) * BLOCK, original_userdata_last_lba=last,
        root_index=slot + 1, root_name='macosroot', root_unique_guid=str(identity),
        root_first_lba=root_first, root_last_lba=root_end - 1,
        root_bytes=macos_gib * (1 << 30), macos_gib=macos_gib,
        other_partitions_changed=False, userdata_contents_discarded=False,
        userdata_filesystem_rebuilt=False, root_image_written=False, applied=False)


class Device:
    def __init__(self, serial):
        if serial != '29d9c0be':
            raise ValueError('select the qualified sheng serial')
        self.serial, self.adb = serial, ['adb', '-s', serial]
        self.require_recovery()
        if int(self.shell('cat /sys/block/sda/queue/logical_block_size')) != BLOCK:
            raise ValueError('unexpected UFS LUN0 block size')
        self.lbas = int(self.shell('cat /sys/block/sda/size')) * 512 // BLOCK
        if self.lbas != 64007168:
            raise ValueError('LUN0 capacity differs from the recorded sheng')

    def shell(self, command, *, timeout=30):
        return subprocess.check_output(self.adb + ['shell', command], text=True, timeout=timeout).strip()

    def require_recovery(self):
        if (subprocess.check_output(self.adb + ['get-state'], text=True, timeout=10).strip() != 'recovery'
                or self.shell('id -u') != '0' or self.shell('getprop ro.product.device') != 'sheng'):
            raise ValueError('requires root ADB in the selected sheng Recovery')
        mounts = self.shell('cat /proc/mounts')
        if any(line.split()[1] in ('/data', '/metadata') or '/dev/block/sda' in line for line in mounts.splitlines()):
            raise ValueError('userdata, metadata and LUN0 partitions must be unmounted')
        if self.shell('ls -A /sys/class/block/sda29/holders'):
            raise ValueError('userdata still has an active device-mapper holder')

    def read(self, start, count):
        data = subprocess.check_output(self.adb + ['exec-out', 'sh', '-c',
            f'dd if=/dev/block/sda bs={BLOCK} skip={start} count={count} 2>/dev/null'], timeout=120)
        if len(data) != count * BLOCK:
            raise ValueError('incomplete UFS read')
        return data

    def write(self, path, start, count):
        if path.stat().st_size != count * BLOCK:
            raise ValueError('unexpected GPT write size')
        remote = '/tmp/sheng-root-' + path.name
        subprocess.run(self.adb + ['push', str(path), remote], check=True, timeout=60, stdout=subprocess.DEVNULL)
        try:
            self.shell(f'dd if={shlex.quote(remote)} of=/dev/block/sda bs={BLOCK} seek={start} count={count} conv=notrunc && sync')
            if self.read(start, count) != path.read_bytes():
                raise ValueError('GPT write readback differs; keep Recovery and rollback files')
        finally:
            self.shell('rm -f ' + shlex.quote(remote))


def prepare(device, directory, macos_gib):
    primary = device.read(0, WINDOW // BLOCK)
    secondary = device.read(device.lbas - WINDOW // BLOCK, WINDOW // BLOCK)
    baseline = (ROOT / 'private/backups/20261023-gpt-boot/sda-primary.bin').read_bytes()
    before = geometry(primary, device.lbas, 0)
    old = geometry(baseline, device.lbas, 0)
    if before[1][56:72] != old[1][56:72] or before[2] != old[2]:
        raise ValueError('current LUN0 layout differs from the saved baseline')
    result, record = layout(primary, secondary, device.lbas, macos_gib)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, data in (('before-primary.bin', primary), ('before-secondary.bin', secondary),
                       ('after-primary.bin', result['primary']), ('after-secondary.bin', result['secondary'])):
        (directory / name).write_bytes(data)
    record.update(serial=device.serial, prepared_at=datetime.now(timezone.utc).isoformat(),
                  before=dict(primary=sha(primary), secondary=sha(secondary)))
    (directory / 'plan.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def apply(device, directory):
    record = json.loads((directory / 'plan.json').read_text())
    if record['applied'] or record['serial'] != device.serial or record['disk_lbas'] != device.lbas:
        raise ValueError('stale or already applied destructive plan')
    device.require_recovery()
    for name, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        raw = device.read(start, WINDOW // BLOCK)
        if sha(raw) != record['before'][name] or raw != (directory / f'before-{name}.bin').read_bytes():
            raise ValueError('LUN0 changed after preparation')
        parse_gpt((directory / f'after-{name}.bin').read_bytes(), BLOCK, device.lbas, start)
    journal = directory / 'apply.jsonl'
    if journal.exists():
        raise ValueError('previous write attempt exists; inspect it before retrying')
    with journal.open('x') as log:
        for name, window in (('secondary', device.lbas - WINDOW // BLOCK), ('primary', 0)):
            data = (directory / f'after-{name}.bin').read_bytes()
            _, header, entries, start, _, _ = geometry(data, device.lbas, window)
            count = (len(entries) + BLOCK - 1) // BLOCK
            payload = data[(start - window) * BLOCK:(start - window + count) * BLOCK]
            for kind, content, at, length in (('array', payload, start, count),
                                              ('header', header, 1 if name == 'primary' else device.lbas - 1, 1)):
                path = directory / f'write-{name}-{kind}.bin'
                path.write_bytes(content)
                log.write(json.dumps(dict(operation='starting', copy=name, kind=kind, lba=at, count=length)) + '\n');log.flush()
                device.write(path, at, length)
                log.write(json.dumps(dict(operation='verified', copy=name, kind=kind)) + '\n');log.flush()
    for name, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        data = device.read(start, WINDOW // BLOCK)
        if data != (directory / f'after-{name}.bin').read_bytes():
            raise ValueError('complete GPT readback differs')
        (directory / f'verified-{name}.bin').write_bytes(data)
    record.update(applied=True, gpt_readback_verified=True, recovery_reboot_required=True)
    (directory / 'plan.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--macos-gib', type=int, choices=(32, 64), default=64)
    parser.add_argument('--apply-discard-userdata', action='store_true')
    args = parser.parse_args()
    device = Device(args.serial)
    result = apply(device, args.output) if args.apply_discard_userdata else prepare(device, args.output, args.macos_gib)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
