#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Back up GPT copies and boot partitions through root recovery ADB; never writes the device."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
PARTITIONS = [f'{name}_{slot}' for name in ('boot', 'init_boot', 'vendor_boot', 'recovery', 'dtbo',
                                           'vbmeta', 'vbmeta_system', 'uefi') for slot in ('a', 'b')]


def parse_gpt(data, block, device_lbas, start_lba):
    relative_header = (1 if start_lba == 0 else device_lbas - 1) - start_lba
    offset = relative_header * block
    header = bytearray(data[offset:offset+block])
    if header[:8] != b'EFI PART':
        raise ValueError('GPT signature missing')
    size, expected = struct.unpack_from('<II', header, 12)
    if not 92 <= size <= block:
        raise ValueError('invalid GPT header size')
    struct.pack_into('<I', header, 16, 0)
    if zlib.crc32(header[:size]) != expected:
        raise ValueError('GPT header CRC mismatch')
    current, other, first, last = struct.unpack_from('<QQQQ', header, 24)
    if current != start_lba + relative_header or not 0 <= other < device_lbas or not 1 < first <= last < device_lbas - 1:
        raise ValueError('invalid GPT geometry')
    entries_lba, count, stride, crc = struct.unpack_from('<QIII', header, 72)
    if count > 4096 or stride < 128 or stride % 8:
        raise ValueError('invalid GPT entry geometry')
    begin = (entries_lba - start_lba) * block
    end = begin + count * stride
    if begin < 0 or end > len(data):
        raise ValueError('GPT entry array outside backup window')
    entries = data[begin:end]
    if zlib.crc32(entries) != crc:
        raise ValueError('GPT entry CRC mismatch')
    partitions = []
    for i in range(count):
        entry = entries[i*stride:(i+1)*stride]
        if entry[:16] == bytes(16):
            continue
        lo, hi = struct.unpack_from('<QQ', entry, 32)
        if not first <= lo <= hi <= last:
            raise ValueError('partition lies outside usable GPT LBAs')
        name = entry[56:128].decode('utf-16-le').split('\0', 1)[0]
        partitions.append(dict(name=name, first_lba=lo, last_lba=hi))
    ordered = sorted(partitions, key=lambda p:p['first_lba'])
    if any(a['last_lba'] >= b['first_lba'] for a,b in zip(ordered, ordered[1:])):
        raise ValueError('overlapping GPT partitions')
    return dict(current_lba=current, backup_lba=other, first_usable=first,
                last_usable=last, partitions=partitions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial')
    parser.add_argument('--output', type=Path, default=ROOT / 'private/backups')
    args = parser.parse_args()
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])
    def shell(cmd):
        return subprocess.check_output([*adb, 'shell', cmd], text=True, timeout=15).strip()
    if shell('id -u') != '0' or shell('getprop ro.product.device') != 'sheng':
        raise ValueError('requires root ADB on sheng')
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / 'manifest.json').exists():
        raise ValueError('backup manifest already exists; choose another output to preserve it')
    manifest = dict(format=1, data_backed_up=False, device_writes=False, gpt={}, images={})
    def save(cmd, name, length):
        if length <= 0 or length > 512 << 20:
            raise ValueError('backup length outside bounded partition limit')
        path = args.output / name
        if path.exists():
            raise ValueError(f'will not overwrite {name}')
        temporary = path.with_suffix(path.suffix + '.partial')
        with temporary.open('xb') as target:
            subprocess.run([*adb, 'exec-out', 'sh', '-c', f'{cmd} 2>/dev/null'],
                           stdout=target, check=True, timeout=180)
        if temporary.stat().st_size != length:
            raise ValueError(f'{name}: incomplete raw read')
        with temporary.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        temporary.rename(path)
        return dict(file=name, bytes=length, sha256=digest)
    for lun in ('sda', 'sdb', 'sdc', 'sdd', 'sde', 'sdf'):
        block = int(shell(f'cat /sys/block/{lun}/queue/logical_block_size'))
        sectors512 = int(shell(f'cat /sys/block/{lun}/size'))
        if block not in (512, 4096) or sectors512 * 512 % block:
            raise ValueError('unsupported UFS geometry')
        lbas = sectors512 * 512 // block
        windows = {}
        # One MiB covers the bounded 4096-entry GPT array plus its header.
        count = min((1 << 20) // block, lbas // 2)
        for kind, start in (('primary', 0), ('secondary', lbas - count)):
            record = save(f'dd if=/dev/block/{lun} bs={block} skip={start} count={count}',
                          f'{lun}-{kind}.bin', block * count)
            record['gpt'] = parse_gpt((args.output / record['file']).read_bytes(), block, lbas, start)
            windows[kind] = record
        a,b = windows['primary']['gpt'], windows['secondary']['gpt']
        if a['partitions'] != b['partitions'] or a['backup_lba'] != b['current_lba'] or b['backup_lba'] != a['current_lba']:
            raise ValueError(f'{lun}: GPT copies disagree')
        manifest['gpt'][lun] = dict(logical_block_bytes=block, device_lbas=lbas, copies=windows)
        print(f'PASS {lun}: both GPT headers and arrays verified', flush=True)
    for name in PARTITIONS:
        path = '/dev/block/by-name/' + name
        target = shell(f'readlink -f {path}')
        if not re.fullmatch('/dev/block/sd[a-f][0-9]+', target):
            raise ValueError(f'invalid block path for {name}')
        partition = target.rsplit('/',1)[-1]
        size = int(shell(f'cat /sys/class/block/{partition}/size')) * 512
        record = save(f'dd if={path} bs=1048576', name+'.img', size)
        # Read twice: local hash alone does not establish agreement with the device.
        remote_hash = shell(f'sha256sum {path}').split()[0]
        if remote_hash != record['sha256']:
            raise ValueError(f'{name}: device read-back hash differs')
        manifest['images'][name] = record
        print(f'PASS {name}: raw backup and device hash agree', flush=True)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Backup complete. Android userdata has NOT been backed up; repartitioning remains blocked.')


if __name__ == '__main__':
    main()
