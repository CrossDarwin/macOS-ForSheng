# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from package_reference_xnu import audit_kernel, vendor_dtbs


class ReferenceKernel(unittest.TestCase):
    def image(self):
        base = 0xfffffff007004000
        segment = struct.pack('<II16sQQQQiiII', 0x19, 72, b'__TEXT', base, 0x2000, 0, 0x2000, 5, 5, 0, 0)
        deployment = struct.pack('<6I', 0x32, 24, 2, 0x110000, 0x1b0000, 0)
        thread = bytearray(struct.pack('<4I', 5, 288, 6, 68) + bytes(272))
        struct.pack_into('<Q', thread, 272, base + 0x1000)
        commands = segment + deployment + thread
        data = bytearray(0x2000)
        data[:32] = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 3, len(commands), 0, 0)
        data[32:32 + len(commands)] = commands
        return data

    def audit(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'kernel.macho'
            path.write_bytes(data)
            return audit_kernel(path)

    def test_reference_and_foreign_abi(self):
        data = self.image()
        self.assertFalse(self.audit(data)['macos27_abi_qualified'])
        for offset, value in ((4, 0x1000007), (8, 2), (32 + 72 + 8, 1), (32 + 72 + 12, 0x120000)):
            modified = bytearray(data)
            struct.pack_into('<I', modified, offset, value)
            with self.assertRaises(ValueError):
                self.audit(modified)

    def test_truncated_commands_and_unbacked_entry(self):
        data = self.image()
        for modified in (data[:32], data[:100], data[:-1]):
            with self.assertRaises(ValueError):
                self.audit(modified)
        struct.pack_into('<Q', data, 32 + 72 + 24 + 272, 0xfffffff080000000)
        with self.assertRaisesRegex(ValueError, 'not file backed'):
            self.audit(data)

    def test_vendor_dtb_extent_and_concatenation(self):
        header = bytearray(4096)
        header[:8] = b'VNDRBOOT'
        struct.pack_into('<5I', header, 8, 4, 4096, 32768, 0x1000000, 0)
        struct.pack_into('<II', header, 2096, 2128, 80)
        fdt = struct.pack('>II', 0xd00dfeed, 40) + bytes(32)
        image = header + fdt * 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'vendor_boot.img'
            path.write_bytes(image)
            self.assertEqual(vendor_dtbs(path), fdt * 2)
            for damaged in (image[:-1], image[:4096] + bytes(80), image[:4136] + fdt[:4] + bytes(36)):
                path.write_bytes(damaged)
                with self.assertRaises(ValueError):
                    vendor_dtbs(path)
