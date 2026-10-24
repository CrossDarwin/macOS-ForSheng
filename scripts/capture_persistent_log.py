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

from decode_native_log import decode, SIZE
from decode_xnu_panic import save as save_panic
from observe_macos26_kernel import identify

PARTITION = '4cd2ed34-2142-4ea4-abf2-ec6c51d117d7'


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
    if (not panic_size and panic or any(at & 0x3fff or not 0x880000000 <= at < at + length <= 0x8bb300000
                                      for at, length in spans)
            or panic_size and max(address, panic) < min(address + log_size, panic + panic_size)):
        raise ValueError('capture request RAM bounds differ')
    return dict(uuid=str(uuid.UUID(bytes=identity)).upper(), log_pa=hex(address),
                panic_pa=hex(panic), panic_bytes=panic_size)


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

    state = adb('shell', 'id -u; getprop ro.product.device; getprop ro.bootmode').splitlines()
    if state != ['0', 'sheng', 'recovery']:
        raise ValueError(f'root sheng Recovery required, observed {state!r}')
    probe = adb('shell', 'readlink -f /dev/block/by-name/macoslog; blockdev --getsize64 /dev/block/by-name/macoslog; blkid /dev/block/by-name/macoslog')
    lines = probe.splitlines()
    if (lines[:2] != ['/dev/block/sde78', '67108864'] or 'TYPE="vfat"' not in probe
            or 'LABEL="MACOSLOG"' not in probe):
        raise ValueError('macoslog device, size or FAT label differs')
    args.output.mkdir(parents=True)
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
    result = dict(device=args.serial, kernel_uuid=native['uuid'], read_only_mount=True,
                  captures=captures, raw_files_preserved=True,
                  warm_reboot_retention_qualified=False, run_freshness_qualified=False)
    (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
