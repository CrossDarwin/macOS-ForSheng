#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode a stopped SHENG console snapshot against its linked kernel UUID."""
import argparse
import json
from pathlib import Path
import struct
import uuid

HEADER = 128
PREFIX = 16384
TAIL = 65536
SIZE = HEADER + PREFIX + TAIL


def decode(data: bytes, expected_uuid: str) -> tuple[bytes, dict]:
    if len(data) != SIZE:
        raise ValueError('native log snapshot is truncated or has an unknown extent')
    fields = struct.unpack_from('<8s4I2Q2I8Q16s', data)
    if fields[:5] != (b'SHNLOG01', 1, HEADER, PREFIX, TAIL):
        raise ValueError('unknown native log layout')
    total, dropped, writer, panic = fields[5:9]
    if writer not in (0, 1) or panic not in (0, 1, 2, 3):
        raise ValueError('invalid native log state')
    identity = str(uuid.UUID(bytes=fields[-1])).upper()
    if identity != expected_uuid.upper():
        raise ValueError('RAM log UUID differs from the linked kernel; preserve the raw capture')
    prefix_len = min(total, PREFIX)
    start = max(prefix_len, total - TAIL)
    # An interrupted writer may have overwritten the oldest tail byte before
    # committing total. Omit that byte instead of presenting it as valid.
    if writer and total >= TAIL and start == total - TAIL:
        start += 1
    omitted = start - prefix_len
    text = data[HEADER:HEADER + prefix_len]
    if omitted:
        text += f'\n[... {omitted} committed console bytes not retained ...]\n'.encode()
    ring = data[HEADER + PREFIX:]
    offset = start % TAIL
    kept = total - start
    text += (ring[offset:] + ring[:offset])[:kept]
    if dropped:
        text += f'\n[... {dropped} console bytes dropped by busy writer ...]\n'.encode()
    names = ('physical_base', 'panic_caller', 'panic_sp', 'elr_el1', 'esr_el1',
             'far_el1', 'mpidr_el1', 'kernel_image_va')
    if panic == 3:
        names = ('physical_base', 'fault_pc', 'fault_sp', 'elr_el1', 'esr_el1',
                 'far_el1', 'mpidr_el1', 'kernel_image_va')
    report = dict(uuid=identity, total_bytes=total, retained_bytes=prefix_len + kept,
                  omitted_bytes=omitted, busy_dropped_bytes=dropped,
                  writer_interrupted=bool(writer), panic_state=panic,
                  complete=not (omitted or dropped or writer),
                  registers={name: hex(value) for name, value in zip(names, fields[9:17])},
                  register_boundary=('first EL1 synchronous exception before the normal vector prologue' if panic == 3 else
                                     'panic caller and registers at capture hook; not necessarily the original fault state'),
                  warm_reboot_retention_qualified=False, hardware_transport_qualified=False)
    return text, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from observe_macos26_kernel import identify
    _, _, kernel = identify(args.kernel_build.resolve())
    raw = args.snapshot.read_bytes()
    text, report = decode(raw, kernel['uuid'])
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'console.bin').write_bytes(raw)
    (args.output / 'console.txt').write_bytes(text)
    (args.output / 'console.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
