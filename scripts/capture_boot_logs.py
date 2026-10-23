#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Capture bounded Qualcomm boot logs through root recovery ADB, or decode a saved capture."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LIMITS = {'logfs': 32 << 20, 'xbl_sc_logs': 4 << 20, 'rawdump': 1 << 20}


def decode_log(data: bytes) -> str:
    # ASCII logs also have zero-filled tails; inspect character positions before trimming.
    prefix = data[:256]
    if len(prefix) >= 4 and prefix[1::2].count(0) > len(prefix[1::2]) * .75:
        if len(data) % 2:
            data = data[:-1]
        return data.decode('utf-16-le', errors='replace').rstrip('\0')
    return data.rstrip(b'\0').decode('utf-8', errors='replace')


def save(path: Path, data: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(data)
    path.chmod(0o600)


def decode_capture(directory: Path) -> dict:
    results = {}
    logfs = directory / 'logfs.bin'
    if logfs.exists():
        # Fixed file names avoid extracting arbitrary archive paths onto the host.
        for index in range(5):
            name = f'UefiLog{index}.txt'
            result = subprocess.run(['7z', 'e', '-so', str(logfs), name],
                                    capture_output=True, timeout=30)
            if result.returncode not in (0, 1) or not 0 < len(result.stdout) <= 1 << 20:
                raise ValueError(f'could not extract bounded {name}: {result.stderr.decode(errors="replace")}')
            text = decode_log(result.stdout)
            save(directory / f'UefiLog{index}-decoded.txt', text.encode())
            results[name] = {
                'lines': len(text.splitlines()),
                'diagnostics': [line for line in text.splitlines() if any(token in line for token in (
                    'Handling Cmd: boot', 'Boot image header OS version', 'LoadImageAndAuthVB2',
                    'HandleActiveSlotUnbootable', 'Switching the boot lun', 'Footer SecPatch'))],
            }
    for name in ('xbl_sc_logs', 'rawdump'):
        path = directory / f'{name}.bin'
        if path.exists():
            strings = re.findall(rb'[\x20-\x7e]{8,}', path.read_bytes())
            save(directory / f'{name}-strings.txt', b'\n'.join(strings) + b'\n')
    report = {'uefi_logs': results, 'log_ring_order_inferred': False,
              'rawdump_attributed_to_current_boot': False,
              'note': 'These are firmware-owned logs; they do not establish execution of the experimental UEFI probe.'}
    save(directory / 'decode.json', (json.dumps(report, indent=2) + '\n').encode())
    return report


def capture(serial: str | None, output: Path) -> None:
    adb = ['adb'] + (['-s', serial] if serial else [])

    def shell(command: str) -> str:
        return subprocess.check_output([*adb, 'shell', command], text=True, timeout=20).strip()

    if shell('id -u') != '0' or shell('getprop ro.product.device') != 'sheng':
        raise ValueError('requires root recovery ADB on sheng')
    if shell('getprop ro.bootmode') != 'recovery' and not shell('pidof recovery || true'):
        raise ValueError('device is not identified as recovery; preserve boot logs before starting Android')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = {'captured_at': datetime.now(timezone.utc).isoformat(),
              'device_writes': False, 'partitions': {}}
    for name, limit in LIMITS.items():
        device = f'/dev/block/by-name/{name}'
        target = shell(f'readlink -f {device}')
        if not re.fullmatch(r'/dev/block/sd[a-f][0-9]+', target):
            raise ValueError(f'{name}: unexpected block device')
        partition = target.rsplit('/', 1)[-1]
        size = int(shell(f'cat /sys/class/block/{partition}/size')) * 512
        length = min(size, limit)
        if size <= 0 or (name != 'rawdump' and size > limit) or length % 4096:
            raise ValueError(f'{name}: unexpected partition size {size}')
        command = f'dd if={device} bs=4096 count={length // 4096} 2>/dev/null'
        data = subprocess.check_output([*adb, 'exec-out', 'sh', '-c', command], timeout=120)
        if len(data) != length:
            raise ValueError(f'{name}: incomplete partition read')
        digest = hashlib.sha256(data).hexdigest()
        remote = shell(f'{command} | sha256sum').split()[0]
        if remote != digest:
            raise ValueError(f'{name}: device and host hashes differ')
        save(output / f'{name}.bin', data)
        report['partitions'][name] = {'bytes': length, 'partition_bytes': size,
                                      'head_only': length < size, 'sha256': digest}
        # Preserve verified reads even if a later partition is unavailable.
        manifest = output / 'manifest.json'
        manifest.write_text(json.dumps(report, indent=2) + '\n')
        manifest.chmod(0o600)
        print(f'PASS {name}: {length} bytes, device hash agrees', flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial')
    parser.add_argument('--output', type=Path, help='new private capture directory')
    parser.add_argument('--decode-only', type=Path, help='decode existing raw files without accessing a device')
    args = parser.parse_args()
    if args.decode_only:
        if args.output or args.serial:
            parser.error('--decode-only cannot be combined with capture options')
        directory = args.decode_only.resolve()
    else:
        if not args.output:
            parser.error('--output is required when capturing')
        directory = args.output.resolve()
        if not directory.is_relative_to((ROOT / 'private').resolve()):
            parser.error('raw device logs must be kept under the ignored private directory')
        capture(args.serial, directory)
    print(json.dumps(decode_capture(directory), indent=2))


if __name__ == '__main__':
    main()
