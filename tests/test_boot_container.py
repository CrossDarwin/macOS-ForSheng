# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'sheng_v4', ROOT / 'UniXNU-sheng/scripts/package-sheng-boot-v4.py')
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)
shim_spec = importlib.util.spec_from_file_location(
    'sheng_shim', ROOT / 'UniXNU-sheng/scripts/package-sheng-boot.py')
shim = importlib.util.module_from_spec(shim_spec)
shim_spec.loader.exec_module(shim)


class BootContainer(unittest.TestCase):
    def test_fd_address_is_not_an_image_load_offset(self):
        data = bytearray(192)
        data[56:60] = b'ARM\x64'
        struct.pack_into('<QQQ', data, 8, 0, len(data) + 0x300000, 0xA)
        self.assertEqual(shim.image_header(data, 0x300000, 0, 0xA)['text_offset'], 0)
        with self.assertRaises(ValueError):
            shim.image_header(data, 0x300000, 0xA7100000, 0xA)
        struct.pack_into('<Q', data, 8, 0xA7100000)
        with self.assertRaises(ValueError):
            shim.image_header(data, 0x300000, 0, 0xA)
        struct.pack_into('<Q', data, 8, 0)
        struct.pack_into('<Q', data, 16, 0x300000)
        with self.assertRaises(ValueError):
            shim.image_header(data, 0x300000, 0, 0xA)

    def image(self):
        stock = dict(ramdisk_size=0, signature_size=0, os_version=0,
                     header_size=1584, reserved=[0] * 4, cmdline='')
        payload = b'fixture payload'
        header = v4.build_v4_header(len(payload), stock)
        image = header.ljust(4096, b'\0') + payload.ljust(4096, b'\0')
        return stock, payload, image

    def test_v4_container_roundtrip(self):
        _, payload, image = self.image()
        self.assertEqual(v4.parse_image(image)['kernel'], payload)
        self.assertEqual(struct.unpack_from('<I', image, 40)[0], 4)

    def test_missing_payload_bytes_are_rejected(self):
        _, _, image = self.image()
        for truncated in (image[:100], image[:4096], image[:-1]):
            with self.assertRaises((ValueError, SystemExit)):
                v4.parse_image(truncated)
        with self.assertRaises(SystemExit):
            v4.parse_image(image + b'unexpected trailing bytes')

    def test_claimed_ramdisk_and_signature_are_rejected(self):
        stock, _, image = self.image()
        for field, offset in (('ramdisk_size', 12), ('signature_size', 1580)):
            with self.assertRaises(ValueError):
                v4.build_v4_header(1, stock | {field: 4096})
            corrupted = bytearray(image)
            struct.pack_into('<I', corrupted, offset, 4096)
            with self.assertRaises(ValueError):
                v4.parse_image(corrupted)


if __name__ == '__main__':
    unittest.main()
