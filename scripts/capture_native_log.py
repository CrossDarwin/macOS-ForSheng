#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Save a native log reader's read-only USB export, then decode its kernel UUID."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import zlib

from decode_native_log import SIZE, decode


def capture(directory: Path, reader: dict, output: Path) -> dict:
    status = (directory / 'STATUS.TXT').read_text().rstrip('\0 \r\n')
    fields = dict(line.split('=', 1) for line in status.splitlines() if '=' in line)
    if (fields.get('reader') != reader['reader'] or fields.get('ufs_opened') != 'false'
            or int(fields.get('physical_base', '0'), 0) != reader['physical_base']
            or int(fields.get('bytes', '0')) != SIZE):
        raise ValueError('USB export does not match the selected native reader')
    raw = (directory / 'NATIVLOG.BIN').read_bytes()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / 'console.bin').write_bytes(raw)
    (output / 'reader-status.txt').write_text(status + '\n')
    # Preserve bytes even if firmware overwrote RAM or the captured build differs.
    report = dict(decoded=False, reader_errno=int(fields['errno']),
                  current_boot_freshness_qualified=False, retention_qualified=False)
    try:
        if report['reader_errno'] or len(raw) != SIZE or f'{zlib.crc32(raw):08x}' != fields['crc32']:
            raise ValueError('reader mapping, length or USB snapshot CRC failed')
        text, native = decode(raw, reader['kernel_uuid'])
        (output / 'console.txt').write_bytes(text)
        report.update(decoded=True, native=native, reader_crc_verified=True)
    except ValueError as error:
        report['error'] = str(error)
    if reader.get('panic_bytes'):
        try:
            panic = (directory / 'XNUPANIC.BIN').read_bytes()
            (output / 'xnu-panic.bin').write_bytes(panic)
            if (int(fields.get('panic_physical_base', '0'), 0) != reader['panic_physical_base']
                    or int(fields.get('panic_bytes', '0')) != reader['panic_bytes']
                    or int(fields.get('panic_errno', '-1'))
                    or len(panic) != reader['panic_bytes']
                    or f'{zlib.crc32(panic):08x}' != fields.get('panic_crc32')):
                raise ValueError('panic reader range, mapping or USB snapshot CRC failed')
            from decode_xnu_panic import save
            report['panic'] = save(output, panic, reader['kernel_uuid'])
        except (ValueError, OSError) as error:
            report['panic'] = dict(decoded=False, error=str(error))
    (output / 'capture.json').write_text(json.dumps(report, indent=2) + '\n')
    for path in output.iterdir():
        path.chmod(0o600)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader-build', type=Path, required=True)
    parser.add_argument('--directory', type=Path, help='already mounted SHENGNATLOG disk')
    parser.add_argument('--wait', type=int, default=45)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.wait <= 300:
        parser.error('--wait must be between 1 and 300 seconds')
    reader = json.loads(args.reader_build.read_text())
    if reader.get('reader') not in ('sheng-native-reader-v1', 'sheng-native-reader-v2') or reader.get('ufs_access') is not False:
        raise ValueError('requires the native read-only RAM reader build record')
    directory = args.directory
    deadline = time.monotonic() + args.wait
    while directory is None and time.monotonic() < deadline:
        link = Path('/dev/disk/by-label/SHENGNATLOG')
        if not link.exists():
            time.sleep(0.5)
            continue
        device = str(link.resolve())
        info = json.loads(subprocess.check_output(
            ['lsblk', '-J', '-b', '-o', 'PATH,TRAN,RO,SIZE,MOUNTPOINTS', device], text=True))['blockdevices'][0]
        if info['tran'] != 'usb' or not info['ro'] or info['size'] != 1048576:
            raise ValueError('USB export has unexpected size, transport or write access')
        mounts = [mount for mount in info['mountpoints'] if mount]
        if mounts:
            directory = Path(mounts[0])
        else:
            subprocess.run(['udisksctl', 'mount', '--no-user-interaction', '-b', device, '-o', 'ro'], check=True)
    if directory is None:
        raise SystemExit('native RAM reader USB disk did not appear')
    report = capture(directory, reader, args.output)
    print(json.dumps(report, indent=2))
    panic = report.get('panic', {})
    if (not report['decoded'] or panic.get('error')
            or (panic.get('initialized') and not panic.get('complete'))):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
