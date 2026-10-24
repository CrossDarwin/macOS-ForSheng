#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pull macoslog read-only from root Recovery and decode matching native captures."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import uuid
import zlib

from backup_device import parse_gpt
from decode_native_log import decode, SIZE
from decode_xnu_panic import save as save_panic
from observe_macos26_kernel import identify

PARTITION = '4cd2ed34-2142-4ea4-abf2-ec6c51d117d7'
# 与固件恢复器使用相同的sheng实际RAM表，保留两段之间的禁读间隔
RAM_RANGES = ((0x880000000, 0x8bb300000), (0x8c0000000, 0xa00000000))


def request(data: bytes) -> dict:
    if len(data) != 80:
        raise ValueError('unknown capture request size')
    magic, version, size, address, log_size, panic_size, panic, identity, partition, checksum, reserved = struct.unpack('<8sIIQIIQ16s16sII', data)
    checked = bytearray(data)
    checked[72:76] = bytes(4)
    if (magic != b'SHNSAVE1' or version != 1 or size != 80 or reserved
            or log_size != SIZE or panic_size not in (0, 524288)
            or str(uuid.UUID(bytes_le=partition)) != PARTITION
            or zlib.crc32(checked) != checksum):
        raise ValueError('capture request identity, layout or CRC differs')
    spans = [(address, log_size)] + ([(panic, panic_size)] if panic_size else [])
    if (not panic_size and panic or any(at & 0x3fff or not any(start <= at < at + length <= end for start, end in RAM_RANGES)
                                      for at, length in spans)
            or panic_size and max(address, panic) < min(address + log_size, panic + panic_size)):
        raise ValueError('capture request RAM bounds differ')
    return dict(uuid=str(uuid.UUID(bytes=identity)).upper(), log_pa=hex(address),
                panic_pa=hex(panic), panic_bytes=panic_size)


def status_record(data: bytes, magic: bytes) -> dict:
    if len(data) != 16 or data[:8] != magic:
        raise ValueError('unknown loader status record')
    value, = struct.unpack_from('<Q', data, 8)
    names = {0: 'Success', 2: 'Invalid Parameter', 3: 'Unsupported', 5: 'Buffer Too Small',
             7: 'Device Error', 8: 'Write Protected', 9: 'Out Of Resources', 10: 'Volume Corrupted',
             11: 'Volume Full', 14: 'Not Found', 17: 'No Mapping', 18: 'Timeout',
             20: 'Already Started', 27: 'CRC Error', 33: 'Compromised Data'}
    error = bool(value & (1 << 63))
    code = value & ~(1 << 63)
    name = names.get(code, 'Unknown') if error or value == 0 else 'Warning'
    return dict(status=hex(value), name=name, error=error,
                capture_verified=False, run_freshness_qualified=False)


def inspect_capture(directory: Path, kernel_uuid: str) -> dict:
    if (directory / 'DONE.TXT').read_bytes() != b'SHENG capture complete\r\n':
        raise ValueError('capture has no verified completion marker')
    info = request((directory / 'REQUEST.BIN').read_bytes())
    if info['uuid'] != kernel_uuid:
        raise ValueError('capture belongs to another kernel UUID; raw files preserved')
    text, log = decode((directory / 'NATIVE.BIN').read_bytes(), kernel_uuid)
    if log['registers']['physical_base'] != info['log_pa']:
        raise ValueError('native log PA differs from the saved request')
    if info['panic_bytes'] and (directory / 'PANIC.BIN').stat().st_size != info['panic_bytes']:
        raise ValueError('panic snapshot is truncated')
    # Compare the EFI export against the existing ring decoder, preserving both files.
    exported = (directory / 'CONSOLE.TXT').read_bytes()
    if exported != text:
        raise ValueError('EFI console export differs from native ring decode')
    (directory / 'console-decoded.txt').write_bytes(text)
    panic = None
    if info['panic_bytes']:
        panic = save_panic(directory, (directory / 'PANIC.BIN').read_bytes(), kernel_uuid)
    result = dict(request=info, native=log, panic=panic, internal_file_capture=True,
                  warm_reboot_retention_qualified=False, run_freshness_qualified=False)
    (directory / 'decoded.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    _, _, native = identify(args.kernel_build.resolve())
    if args.output.exists():
        parser.error('--output must be new; prior captures are never overwritten')

    def adb(*parts: str) -> str:
        return subprocess.check_output(['adb', '-s', args.serial, *parts], text=True, timeout=120).strip()

    state = [adb('get-state')] + adb('shell', 'id -u; getprop ro.product.device').splitlines()
    if state != ['recovery', '0', 'sheng']:
        raise ValueError(f'root sheng Recovery required, observed {state!r}')
    probe = adb('shell', 'readlink -f /dev/block/by-name/macoslog; blockdev --getsize64 /dev/block/by-name/macoslog; cat /sys/block/sde/queue/logical_block_size; blockdev --getsize64 /dev/block/sde').splitlines()
    if probe[:3] != ['/dev/block/sde78', '67108864', '4096'] or len(probe) != 4:
        raise ValueError('macoslog device, extent or logical block size differs')
    disk_lbas = int(probe[3]) // 4096
    def read_block(command: str) -> bytes:
        return subprocess.check_output(['adb', '-s', args.serial, 'exec-out', 'sh', '-c', command], timeout=30)
    gpt = read_block('dd if=/dev/block/sde bs=4096 count=256 2>/dev/null')
    if len(gpt) != 1048576:
        raise ValueError('short GPT identity read')
    parse_gpt(gpt, 4096, disk_lbas, 0)
    entries, count, stride = struct.unpack_from('<QII', gpt, 4096 + 72)
    if count <= 77 or stride < 128:
        raise ValueError('macoslog GPT entry is absent')
    at = entries * 4096 + 77 * stride
    entry = gpt[at:at + stride]
    if (len(entry) != stride or str(uuid.UUID(bytes_le=entry[16:32])) != PARTITION
            or str(uuid.UUID(bytes_le=entry[:16])) != 'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7'
            or struct.unpack_from('<QQ', entry, 32) != (448512, 464895)
            or entry[56:128].decode('utf-16-le').rstrip('\0') != 'macoslog'):
        raise ValueError('macoslog GPT identity differs')
    boot = read_block('dd if=/dev/block/by-name/macoslog bs=4096 count=1 2>/dev/null')
    if (len(boot) != 4096 or boot[43:54].rstrip() != b'MACOSLOG'
            or boot[54:62] != b'FAT16   ' or struct.unpack_from('<H', boot, 11)[0] != 4096):
        raise ValueError('macoslog FAT16 geometry or label differs')
    args.output.mkdir(parents=True, mode=0o700)
    mount = adb('shell', 'mktemp -d /tmp/sheng-log.XXXXXX')
    if not re.fullmatch(r'/tmp/sheng-log\.[A-Za-z0-9]+', mount):
        raise ValueError('Recovery returned an unexpected mount path')
    mounted = False
    try:
        adb('shell', f'mount -t vfat -o ro /dev/block/by-name/macoslog {mount}')
        mounted = True
        subprocess.run(['adb', '-s', args.serial, 'pull', mount + '/.', str(args.output / 'files')],
                       check=True, timeout=120)
    finally:
        if mounted:
            adb('shell', f'umount {mount}')
        adb('shell', f'rmdir {mount}')
    captures = []
    for directory in sorted((args.output / 'files').glob('CAP[0-9][0-9][0-9][0-9][0-9]')):
        if not directory.is_dir():
            continue
        try:
            result = inspect_capture(directory, native['uuid'])
            captures.append(dict(capture=directory.name, decoded=True, complete=result['native']['complete']))
        except (ValueError, OSError) as error:
            captures.append(dict(capture=directory.name, decoded=False, reason=str(error)))
    loader_status = {}
    for name, magic in (('RECOVERY.BIN', b'SHNREC01'), ('ARM.BIN', b'SHNARM01')):
        path = args.output / 'files' / name
        if path.exists():
            try:
                loader_status[name] = status_record(path.read_bytes(), magic)
            except ValueError as error:
                loader_status[name] = dict(decode_error=str(error))
    result = dict(device=args.serial, kernel_uuid=native['uuid'], read_only_mount=True,
                  captures=captures, loader_status=loader_status, raw_files_preserved=True,
                  warm_reboot_retention_qualified=False, run_freshness_qualified=False)
    (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
