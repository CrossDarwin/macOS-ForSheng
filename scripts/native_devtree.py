#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Publish the native EL1 text-protection state in generated Apple DTs."""
from pathlib import Path
import struct
import uuid


def configure_native_text_state(path: Path, *, development_root: bool = False,
                                root_hash: bytes | None = None,
                                boot_volume_uuid: uuid.UUID | None = None) -> None:
    data = path.read_bytes()
    chosen = asmb = auth = 0
    if root_hash is not None and not 16 <= len(root_hash) <= 16384:
        raise ValueError('invalid raw root-hash payload size')

    if boot_volume_uuid is not None and root_hash is None:
        raise ValueError('boot volume identity requires the paired recovery root hash')

    def node(at: int, parents: tuple[str, ...] = ()) -> tuple[bytes, int]:
        nonlocal chosen, asmb, auth
        if len(parents) > 32 or at + 8 > len(data):
            raise ValueError('invalid generated device-tree node')
        count, children = struct.unpack_from('<II', data, at)
        at += 8
        if count > 4096 or children > 4096:
            raise ValueError('excessive generated device-tree counts')
        properties = {}
        encoded = bytearray()
        for _ in range(count):
            start = at
            if at + 36 > len(data):
                raise ValueError('truncated device-tree property')
            key, size = struct.unpack_from('<32sI', data, at)
            key = key.split(b'\0', 1)[0].decode('ascii')
            at += 36
            end = at + ((size + 3) & ~3)
            if end > len(data) or key in properties:
                raise ValueError('invalid or repeated device-tree property')
            properties[key] = data[at:at + size]
            encoded.extend(data[start:end])
            at = end
        name = properties.get('name', b'').rstrip(b'\0').decode('ascii')
        location = (*parents, name)
        def ensure(key: str, value: bytes) -> None:
            nonlocal count
            if key in properties:
                if properties[key] != value:
                    raise ValueError(f'generated tree conflicts with native policy: {key}')
            else:
                encoded.extend(struct.pack('<32sI', key.encode(), len(value)) +
                               value + bytes(-len(value) % 4))
                count += 1

        is_chosen = location == ('device-tree', 'chosen')
        if root_hash is not None and location == ('device-tree', 'chosen', 'secure-boot-hashes'):
            auth += 1
            ensure('system-volume-auth-blob', root_hash)
        if is_chosen:
            chosen += 1
            ensure('kernel-ctrr-to-be-enabled', struct.pack('<I', 0))
            if root_hash is not None:
                ensure('osenvironment', b'recoveryos\0')
            if boot_volume_uuid is not None:
                identity = str(boot_volume_uuid).upper().encode('ascii') + b'\0'
                ensure('boot-uuid', identity)
                ensure('apfs-preboot-uuid', identity)
        if development_root and location == ('device-tree', 'chosen', 'asmb'):
            asmb += 1
            ensure('lp-sip0', struct.pack('<Q', 0))
            ensure('lp-sip1', struct.pack('<I', 1))
        descendants = bytearray()
        for _ in range(children):
            child, at = node(at, location)
            descendants.extend(child)
        if development_root and is_chosen and asmb == 0:
            entries = (('name', b'asmb\0'), ('lp-sip0', struct.pack('<Q', 0)),
                       ('lp-sip1', struct.pack('<I', 1)))
            descendants.extend(struct.pack('<II', len(entries), 0))
            for key, value in entries:
                descendants.extend(struct.pack('<32sI', key.encode(), len(value)) +
                                   value + bytes(-len(value) % 4))
            children += 1
            asmb += 1
        if root_hash is not None and is_chosen and auth == 0:
            entries = (('name', b'secure-boot-hashes\0'), ('system-volume-auth-blob', root_hash))
            descendants.extend(struct.pack('<II', len(entries), 0))
            for key, value in entries:
                descendants.extend(struct.pack('<32sI', key.encode(), len(value)) +
                                   value + bytes(-len(value) % 4))
            children += 1
            auth += 1
        return bytes(struct.pack('<II', count, children) + encoded + descendants), at

    result, end = node(0)
    if (end != len(data) or chosen != 1 or development_root and asmb != 1
            or root_hash is not None and auth != 1):
        raise ValueError('requires one complete generated /chosen node')
    path.write_bytes(result)
