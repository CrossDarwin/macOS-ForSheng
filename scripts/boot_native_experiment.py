#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Boot one packaged native experiment from RAM, refusing an unexpected slot."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess


def boot_once(build: Path, serial: str, expected_slot: str, output: Path) -> dict:
    if expected_slot not in ('a', 'b') or not serial:
        raise ValueError('an explicit serial and expected slot a/b are required')
    metadata = json.loads(build.read_text())
    image = build.parent / 'sheng-macos26-kernel.img'
    if (metadata.get('temporary_ram_boot') is not True
            or metadata.get('partition_images_written') is not False
            or image.stat().st_size != metadata['container_bytes']):
        raise ValueError('requires a complete packaged RAM-only native experiment')
    # One record owns one send; an uncertain USB result must not trigger a retry.
    output.mkdir(parents=True, exist_ok=False)
    record = dict(started_at=datetime.now(timezone.utc).isoformat(), serial=serial,
                  build=str(build.resolve()), expected_slot=expected_slot,
                  container_sha256=metadata['container_sha256'],
                  partition_writes=False, slot_changes=False, boot_attempts=0,
                  status='checking-slot')

    def save() -> None:
        (output / 'deployment.json').write_text(json.dumps(record, indent=2) + '\n')

    def run(arguments: list[str], timeout: int, log: str):
        try:
            result = subprocess.run(['fastboot', '-s', serial, *arguments],
                                    capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            data = ''.join(part.decode(errors='replace') if isinstance(part, bytes) else part
                           for part in (error.stdout, error.stderr) if part)
            (output / log).write_text(data)
            return None
        (output / log).write_text(result.stdout + result.stderr)
        return result

    save()
    result = run(['getvar', 'current-slot'], 15, 'slot-before.txt')
    match = re.search(r'^current-slot:\s*([ab])\s*$', result.stdout + result.stderr,
                      re.MULTILINE) if result is not None and result.returncode == 0 else None
    record['observed_slot'] = match[1] if match else None
    if record['observed_slot'] != expected_slot:
        record['status'] = 'refused-slot-mismatch' if match else 'refused-slot-unavailable'
        save()
        return record
    result = run(['getvar', f'slot-unbootable:{expected_slot}'], 15, 'slot-bootable.txt')
    match = re.search(rf'^slot-unbootable:{expected_slot}:\s*(yes|no)\s*$',
                      result.stdout + result.stderr, re.MULTILINE
                      ) if result is not None and result.returncode == 0 else None
    record['slot_unbootable'] = match[1] if match else None
    if record['slot_unbootable'] != 'no':
        record['status'] = 'refused-slot-unbootable' if match else 'refused-slot-unavailable'
        save()
        return record
    record.update(status='boot-command-running', boot_attempts=1)
    save()
    result = run(['boot', str(image.resolve())], 90, 'fastboot-boot.txt')
    record['returncode'] = result.returncode if result is not None else None
    # A successful transport acknowledgement still needs a screen or kernel log.
    record['status'] = 'boot-acknowledged' if result is not None and result.returncode == 0 else 'boot-unconfirmed'
    record['kernel_execution_confirmed'] = False
    save()
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True, help='packaged build.json')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--expected-slot', choices=('a', 'b'), required=True)
    parser.add_argument('--output', type=Path, required=True, help='new experiment record directory')
    args = parser.parse_args()
    try:
        record = boot_once(args.build, args.serial, args.expected_slot, args.output)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'{error}\n')
    print(f"{record['status']} - {args.output / 'deployment.json'}")
    return 0 if record['status'] == 'boot-acknowledged' else 1


if __name__ == '__main__':
    raise SystemExit(main())
