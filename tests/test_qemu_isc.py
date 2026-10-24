import importlib.util
from pathlib import Path
import struct
import unittest
import uuid
import zlib
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare_qemu_isc',
    Path(__file__).resolve().parents[1] / 'scripts/prepare_qemu_isc.py')
isc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isc)


class FreshIscTests(unittest.TestCase):
    def setUp(self):
        self.size = patch.object(isc, 'SIZE', 65536)
        self.size.start()
        self.addCleanup(self.size.stop)
        self.data = bytearray(65536)
        self.data[32:36] = b'NXSB'
        struct.pack_into('<IQ', self.data, 36, 4096, 16)
        self.data[:8] = isc.checksum(self.data[:4096])
        self.ids = {}
        for number, name in enumerate(isc.ROLES, 1):
            at = number * 4096
            identity = uuid.uuid4()
            self.ids[name] = str(identity)
            struct.pack_into('<I', self.data, at + 24, 13)
            self.data[at + 32:at + 36] = b'APSB'
            self.data[at + 240:at + 256] = identity.bytes
            struct.pack_into('<Q', self.data, at + 264, 1)
            self.data[at + 704:at + 704 + len(name)] = name.encode()
            self.data[at:at + 8] = isc.checksum(self.data[at:at + 4096])

    def test_only_role_and_checksum_change(self):
        result, changed = isc.assign_empty_roles(self.data, self.ids)
        expected = bytearray(self.data)
        self.assertEqual(len(changed), 3)
        for item in changed:
            at = item['offset']
            struct.pack_into('<H', expected, at + 964, isc.ROLES[item['name']])
            expected[at:at + 8] = isc.checksum(expected[at:at + 4096])
        self.assertEqual(result, expected)
        self.assertEqual(struct.unpack_from('<H', self.data, 4096 + 964)[0], 0)

    def test_nonempty_volume_refused(self):
        struct.pack_into('<Q', self.data, 4096 + 184, 1)
        self.data[4096:4104] = isc.checksum(self.data[4096:8192])
        with self.assertRaises(ValueError):
            isc.assign_empty_roles(self.data, self.ids)

    def test_wrong_identity_or_checksum_refused(self):
        identities = dict(self.ids, **{'SHENG-xART': str(uuid.uuid4())})
        with self.assertRaises(ValueError):
            isc.assign_empty_roles(self.data, identities)
        self.data[4096 + 100] ^= 1
        with self.assertRaises(ValueError):
            isc.assign_empty_roles(self.data, self.ids)

    def test_gpt_copies_and_unchanged_payload(self):
        media = b''.join(isc.wrap_gpt(self.data))
        self.assertEqual(media[1 << 20:(1 << 20) + len(self.data)], self.data)
        entries = media[1024:1024 + 16384]
        self.assertEqual(entries, media[-512 - 16384:-512])
        self.assertEqual(entries[:16], isc.ISC_TYPE.bytes_le)
        for at in (512, len(media) - 512):
            header = bytearray(media[at:at + 512])
            expected = struct.unpack_from('<I', header, 16)[0]
            struct.pack_into('<I', header, 16, 0)
            self.assertEqual(zlib.crc32(header[:92]), expected)
            self.assertEqual(struct.unpack_from('<I', header, 88)[0], zlib.crc32(entries))


if __name__ == '__main__':
    unittest.main()
