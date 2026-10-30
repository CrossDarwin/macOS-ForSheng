# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare GPT entries while preserving the current Qualcomm A/B slot state."""
import struct


def baseline_entries_match(current: bytes, baseline: bytes, count: int, stride: int) -> bool:
    if stride < 128 or len(current) != count * stride or len(baseline) != len(current):
        return False
    old = [baseline[i * stride:(i + 1) * stride] for i in range(count)]
    now = [current[i * stride:(i + 1) * stride] for i in range(count)]
    names = {entry[56:128].decode('utf-16-le').split('\0')[0]: i for i, entry in enumerate(old)
             if entry[:16] != bytes(16)}
    for i, saved in enumerate(old):
        entry = now[i]
        if entry == saved:
            continue
        name = saved[56:128].decode('utf-16-le').split('\0')[0]
        if not name.endswith(('_a', '_b')):
            return False
        peer = names.get(name[:-1] + ('b' if name.endswith('_a') else 'a'))
        if peer is None or entry[16:48] + entry[56:] != saved[16:48] + saved[56:]:
            return False
        if sorted((entry[:16], now[peer][:16])) != sorted((saved[:16], old[peer][:16])):
            return False
        changed = struct.unpack_from('<Q', entry, 48)[0] ^ struct.unpack_from('<Q', saved, 48)[0]
        if changed & ~(0xfff << 48):
            return False
    return True
