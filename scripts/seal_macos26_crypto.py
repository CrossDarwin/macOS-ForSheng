#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Populate the normal source-provider POST integrity field after final link."""
import hashlib
import hmac
from pathlib import Path
import struct


def seal(kernel: Path) -> dict:
    data = bytearray(kernel.read_bytes())
    if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 2):
        raise ValueError('requires the locally linked native ARM64 executable')
    if b'_sheng_corecrypto_bootstrap\0' not in data:
        raise ValueError('missing the native provider bootstrap')
    cursor, code, integrity, base = 32, None, None, None
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        kind, length = struct.unpack_from('<II', data, cursor)
        if length < 8 or cursor + length > len(data):
            raise ValueError('invalid Mach-O command extent')
        if kind == 0x19:
            name, va, size, fileoff, filesize = struct.unpack_from('<16s4Q', data, cursor + 8)
            if fileoff + filesize > len(data):
                raise ValueError('truncated kernel segment')
            if name.rstrip(b'\0') == b'__TEXT':
                base = va
            count = struct.unpack_from('<I', data, cursor + 64)[0]
            if length != 72 + 80 * count:
                raise ValueError('invalid Mach-O section table')
            for index in range(count):
                section = cursor + 72 + index * 80
                name, segment, address, size, offset = struct.unpack_from('<16s16sQQI', data, section)
                if name.rstrip(b'\0') == b'__text' and segment.rstrip(b'\0') in (b'__TEXT', b'__TEXT_EXEC') and code is None:
                    code = offset, size, address
                if name.rstrip(b'\0') == b'__fips_hmacs':
                    if integrity is not None or size != 32 or offset + size > len(data):
                        raise ValueError('expected a single 32-byte provider HMAC field')
                    integrity = offset
        cursor += length
    if code is None or integrity is None or base is None:
        raise ValueError('missing provider code or integrity field')
    if code[2] - base != code[0] or code[0] + code[1] > len(data):
        raise ValueError('runtime text mapping differs from the provider POST contract')
    if code[0] <= integrity < code[0] + code[1]:
        raise ValueError('integrity field overlaps hashed instructions')
    # Mirrors 2026-05 fipspost_get_hmac: 32 zero key bytes, first __text section.
    mac = hmac.digest(bytes(32), data[code[0]:code[0] + code[1]], 'sha256')
    data[integrity:integrity + 32] = mac
    kernel.write_bytes(data)
    return dict(kernel_sha256=hashlib.sha256(data).hexdigest(), code_file_offset=hex(code[0]),
                code_bytes=code[1], hmac_file_offset=hex(integrity), hmac_sha256=mac.hex(),
                runtime_post_passed=False)
