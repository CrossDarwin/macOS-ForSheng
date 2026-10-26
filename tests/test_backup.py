# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from backup_device import parse_gpt


class GptTests(unittest.TestCase):
    def fixture(self):
        data = bytearray(4096 * 5)
        entry = bytearray(128)
        entry[:16] = b'\x01' * 16
        struct.pack_into('<QQ', entry, 32, 10, 30)
        entry[56:64] = 'test'.encode('utf-16-le')
        data[8192:8320] = entry
        header = bytearray(92)
        struct.pack_into('<8sIIIIQQQQ16sQIII', header, 0, b'EFI PART', 0x10000, 92, 0, 0,
                         1, 99, 10, 90, bytes(16), 2, 1, 128, zlib.crc32(entry))
        struct.pack_into('<I', header, 16, zlib.crc32(header))
        data[4096:4188] = header
        return data

    def test_valid_primary(self):
        result = parse_gpt(self.fixture(), 4096, 100, 0)
        self.assertEqual(result['partitions'][0], dict(name='test', first_lba=10, last_lba=30))

    def test_corrupt_header_and_entry(self):
        for offset in (4096, 4096 + 32, 8192 + 56):
            image = self.fixture()
            image[offset] ^= 1
            with self.assertRaises(ValueError):
                parse_gpt(image, 4096, 100, 0)

    def test_missing_entry_extent(self):
        with self.assertRaisesRegex(ValueError, 'outside backup window'):
            parse_gpt(self.fixture()[:8192], 4096, 100, 0)
