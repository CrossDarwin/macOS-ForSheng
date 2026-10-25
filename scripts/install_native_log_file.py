#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Back up or install one prepared macoslog FAT image through root Recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import uuid

from create_log_partition import Recovery
from native_log_file import BLOCK, CONTRACT, FILE_BYTES, guard, locate, preserve_allocations

ROOT = Path(__file__).resolve().parents[1]
PARTITION = '/dev/block/sde78'
LENGTH = CONTRACT['partition_blocks']*BLOCK


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(device: Recovery) -> dict[str, bytes]:
    if device.lbas != CONTRACT['disk_blocks']:
        raise ValueError('LUN capacity differs')
    observed = device.shell('readlink -f /dev/block/by-name/macoslog; blockdev --getsize64 /dev/block/sde78').splitlines()
    if observed != [PARTITION, str(LENGTH)]:
        raise ValueError('macoslog node or size differs')
    major, minor = (int(n, 16) for n in device.shell(f'stat -c %t:%T {PARTITION}').split(':'))
    mounted = [line.split()[2] for line in device.shell('cat /proc/self/mountinfo').splitlines()]
    if f'{major}:{minor}' in mounted:
        raise ValueError('macoslog must be unmounted before backup or installation')
    flush(device)
    copies = {}
    for name, start in (('primary', 0), ('secondary', device.lbas-256)):
        raw = device.read(start, 256)
        expected = (ROOT/'private/backups/20261024-macoslog-partition'/f'verified-{name}.bin').read_bytes()
        if raw != expected:
            raise ValueError('current LUN4 GPT differs from the preserved macoslog layout')
        copies[name] = raw
    # Full-copy equality above also preserves every other GPT entry.
    h = copies['primary'][BLOCK:2*BLOCK]
    entries, count, stride = struct.unpack_from('<QII', h, 72)
    at = entries*BLOCK+(CONTRACT['partition_index']-1)*stride
    e = copies['primary'][at:at+stride]
    if (count != 96 or stride != 128 or str(uuid.UUID(bytes_le=e[16:32])) != CONTRACT['partition_uuid']
            or struct.unpack_from('<QQ', e, 32) != (448512, 464895)):
        raise ValueError('macoslog identity differs')
    return copies


def flush(device: Recovery) -> None:
    device.shell(f'blockdev --flushbufs {PARTITION} && blockdev --flushbufs /dev/block/sde')


def read_image(device: Recovery) -> bytes:
    flush(device)
    return device.read(CONTRACT['partition_first'], CONTRACT['partition_blocks'])


def backup(device: Recovery, output: Path) -> dict:
    gpt = identity(device)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    image = read_image(device)
    if (image[43:54] != b'MACOSLOG   ' or image[54:62] != b'FAT16   '
            or struct.unpack_from('<H', image, 11)[0] != BLOCK):
        raise ValueError('existing macoslog is not the expected FAT16 volume')
    (output/'macoslog.img').write_bytes(image)
    for name, data in gpt.items():
        (output/f'gpt-{name}.bin').write_bytes(data)
    result = dict(schema=CONTRACT['schema'], bytes=len(image), image_sha256=sha(image),
                  gpt_sha256={key: sha(value) for key, value in gpt.items()}, device_writes=False)
    (output/'backup.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def install(device: Recovery, candidate: Path, output: Path) -> dict:
    gpt = identity(device)
    record = json.loads((candidate/'build.json').read_text())
    image = (candidate/'macoslog.img').read_bytes()
    first = CONTRACT['partition_first']+locate(image)//BLOCK
    if (record['schema'] != CONTRACT['schema'] or record['image_sha256'] != sha(image)
            or record['partition_uuid'] != CONTRACT['partition_uuid'] or record['file_first_lba'] != first
            or record['file_bytes'] != FILE_BYTES or not record['existing_allocations_preserved']
            or image[locate(image)+FILE_BYTES-BLOCK:locate(image)+FILE_BYTES] != guard(first)):
        raise ValueError('prepared candidate identity or ownership differs')
    current = read_image(device)
    if sha(current) != record['original_image_sha256']:
        raise ValueError('macoslog changed after preparation; preserve the new files before proceeding')
    preserve_allocations(current, image)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output/'before.img').write_bytes(current)
    for name, data in gpt.items():
        (output/f'gpt-{name}.bin').write_bytes(data)
    result = dict(schema=CONTRACT['schema'], partition=PARTITION, file_first_lba=first,
        image_sha256=sha(image), previous_sha256=sha(current), write_attempts=1,
        gpt_writes=False, kernel_log_write_qualified=False, status='write-outcome-unknown')
    manifest = output/'deployment.json'
    manifest.write_text(json.dumps(result, indent=2)+'\n')
    try:
        # A single bounded transfer; never retry an uncertain device write.
        with (candidate/'macoslog.img').open('rb') as source:
            completed = subprocess.run(device.adb+['shell', '-T',
                f'dd of={PARTITION} bs=1048576 count={LENGTH} iflag=count_bytes conv=notrunc,fsync'],
                stdin=source, capture_output=True, timeout=180)
        (output/'transfer.txt').write_bytes(completed.stdout+completed.stderr)
        completed.check_returncode()
        result['status'] = 'write-confirmed-verification-pending'
        manifest.write_text(json.dumps(result, indent=2)+'\n')
        observed = read_image(device)
        result['readback_sha256'] = sha(observed)
        if observed != image or identity(device) != gpt:
            raise ValueError('macoslog readback or preserved GPT differs; no write retry')
        result.update(status='verified', gpt_unchanged=True, existing_allocations_preserved=True)
        manifest.write_text(json.dumps(result, indent=2)+'\n')
        return result
    except BaseException as error:
        result['error'] = str(error)
        manifest.write_text(json.dumps(result, indent=2)+'\n')
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'install'))
    parser.add_argument('--serial', required=True)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT/'private').resolve()):
        parser.error('--output must stay in local private/')
    if args.action == 'install' and not args.candidate:
        parser.error('install requires --candidate')
    device = Recovery(args.serial)
    result = backup(device, args.output) if args.action == 'backup' else install(device, args.candidate, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
