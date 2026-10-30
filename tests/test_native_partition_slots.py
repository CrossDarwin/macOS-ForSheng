# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from native_partition_slots import baseline_entries_match


class PartitionSlots(unittest.TestCase):
    def entries(self):
        entries = []
        for i, name in enumerate(('boot_a', 'boot_b', 'userdata')):
            entry = bytearray(128)
            entry[:16] = bytes([i + 1]) * 16
            entry[16:32] = bytes([i + 10]) * 16
            struct.pack_into('<QQQ', entry, 32, 100 + 10 * i, 109 + 10 * i, i << 48)
            encoded = name.encode('utf-16-le')
            entry[56:56 + len(encoded)] = encoded
            entries.append(entry)
        return entries

    def test_slot_type_exchange_and_boot_flags_preserve_identity(self):
        old = self.entries()
        current = [bytearray(entry) for entry in old]
        current[0][:16], current[1][:16] = old[1][:16], old[0][:16]
        struct.pack_into('<Q', current[0], 48, 0x7b << 48)
        self.assertTrue(baseline_entries_match(b''.join(current), b''.join(old), 3, 128))
        for index, offset in ((0, 16), (0, 32), (0, 48), (2, 48), (0, 56)):
            changed = [bytearray(entry) for entry in current]
            changed[index][offset] ^= 1
            self.assertFalse(baseline_entries_match(b''.join(changed), b''.join(old), 3, 128))
        current[1][:16] = old[1][:16]
        self.assertFalse(baseline_entries_match(b''.join(current), b''.join(old), 3, 128))


if __name__ == '__main__':
    unittest.main()
