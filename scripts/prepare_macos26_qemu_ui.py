#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy a QEMU development ESP and provision its explicit native platform UUID."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile
import uuid

from native_devtree import configure_native_text_state, seed_vm_nvram_uuid


def inspect_identity(path: Path) -> uuid.UUID | None:
    data = path.read_bytes()
    identities: list[bytes] = []
    proxies: list[bytes] = []

    def visit(offset: int, parents: tuple[str, ...] = ()) -> int:
        if len(parents) > 32 or offset + 8 > len(data):
            raise ValueError('Invalid generated device tree')
        count, children = struct.unpack_from('<II', data, offset)
        offset += 8
        if count > 4096 or children > 4096:
            raise ValueError('Excessive generated device tree counts')
        properties: dict[str, bytes] = {}
        for _ in range(count):
            if offset + 36 > len(data):
                raise ValueError('Truncated device tree property')
            key, size = struct.unpack_from('<32sI', data, offset)
            key = key.split(b'\0', 1)[0].decode('ascii')
            offset += 36
            end = offset + ((size + 3) & ~3)
            if end > len(data) or key in properties:
                raise ValueError('Invalid or repeated device tree property')
            properties[key] = data[offset:offset + size]
            offset = end
        name = properties.get('name', b'').rstrip(b'\0').decode('ascii')
        location = (*parents, name)
        if location == ('device-tree', 'options') and 'platform-uuid' in properties:
            identities.append(properties['platform-uuid'])
        if parents == ('device-tree',) and 'nvram-proxy-data' in properties:
            proxies.append(properties['nvram-proxy-data'])
        for _ in range(children):
            offset = visit(offset, location)
        return offset

    if visit(0) != len(data):
        raise ValueError('Trailing device tree data')
    if not identities:
        if any(b'platform-uuid=' in proxy for proxy in proxies):
            raise ValueError('NVRAM identity is missing its options property')
        return None
    if len(identities) != 1 or len(proxies) != 1 or len(identities[0]) != 16:
        raise ValueError('Requires one complete native VM identity')
    identity = uuid.UUID(bytes=identities[0])
    if not identity.int or seed_vm_nvram_uuid(proxies[0], identity) != proxies[0]:
        raise ValueError('Options and NVRAM identities differ or are incomplete')
    return identity


def prepare(source: Path, output: Path, identity: uuid.UUID, *, disable_sleep: bool = False) -> dict[str, object]:
    source = source.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; refusing to replace an ESP')
    output = output.resolve()
    if not identity.int:
        raise ValueError('VM platform UUID cannot be nil')
    relative = Path('EFI/UniXNU/Payloads/kernel.macho.adt')
    previous = inspect_identity(source / relative)
    if previous is not None and previous != identity:
        raise ValueError('Refusing to replace an existing VM identity')
    if not output.parent.is_dir():
        raise ValueError('Output parent must exist')
    if output.is_relative_to(source):
        raise ValueError('Output cannot be inside the source ESP')
    with tempfile.TemporaryDirectory(prefix='.qemu-ui-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'esp'
        shutil.copytree(source, stage)
        configure_native_text_state(stage / relative, development_root=True, platform_uuid=identity,
                                    qemu_disable_sleep=disable_sleep)
        if inspect_identity(stage / relative) != identity:
            raise ValueError('Prepared VM identity failed readback')
        stage.rename(output)
    return dict(source_esp=str(source), prepared_esp=str(output), platform_uuid=str(identity),
                qemu_only=True, synthetic_vm_identity=True, source_esp_modified=False,
                apple_chip_identity_modified=False, kernel_modified=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--esp', required=True, type=Path, help='Existing generated QEMU development ESP')
    parser.add_argument('--output', required=True, type=Path, help='New ESP directory; never overwritten')
    parser.add_argument('--platform-uuid', required=True, type=uuid.UUID, help='Explicit identity of this owned VM')
    parser.add_argument('--disable-sleep', action='store_true', help='Describe unavailable VM sleep through the native /defaults policy')
    args = parser.parse_args()
    try:
        report = prepare(args.esp, args.output, args.platform_uuid, disable_sleep=args.disable_sleep)
        report['native_sleep_disabled'] = args.disable_sleep
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f'Failed to prepare QEMU UI ESP: {error}\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
