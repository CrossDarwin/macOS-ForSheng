# SPDX-License-Identifier: MIT
import json
from pathlib import Path
import struct
import tempfile
import types
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
patch = (ROOT / 'patches/UniXNU/0025-qemu-stream-retained-log.patch').read_text()
addition = patch.split('+++ b/scripts/qemu-entry/retained_log_stream.py\n', 1)[1]
source = ''.join(line[1:] for line in addition.splitlines(keepends=True)
                 if line.startswith('+') and not line.startswith('+++'))
module = types.ModuleType('retained_log_stream')
exec(compile(source, 'retained_log_stream.py', 'exec'), module.__dict__)


class RetainedStream(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.identity = uuid.UUID('68F2CBDB-9E98-3785-A2E1-9613AF4762B6')
        self.base = 0xfffffe0007dc4000
        self.reader = module.RetainedLogStream(self.base, str(self.identity), self.directory)
        self.data = bytes(i % 251 for i in range(240000))

    def packet(self, total, *, writer=0, dropped=0, wrong_uuid=False):
        raw = bytearray(128 + 16384 + 65536)
        struct.pack_into('<8s4I2Q2I', raw, 0, b'SHNLOG01', 1, 128, 16384, 65536,
                         total, dropped, writer, 0)
        raw[112:128] = bytes(16) if wrong_uuid else self.identity.bytes
        prefix = min(total, 16384)
        raw[128:128 + prefix] = self.data[:prefix]
        for i in range(max(0, total - 65536), total):
            raw[128 + 16384 + i % 65536] = self.data[i]
        if writer and total >= 65536:
            raw[128 + 16384 + total % 65536] = 255
        def request(command):
            self.assertTrue(command.startswith('m'))
            address, size = (int(v, 16) for v in command[1:].split(','))
            offset = address - self.base
            self.assertGreaterEqual(offset, 0)
            self.assertLessEqual(offset + size, len(raw))
            return raw[offset:offset + size].hex()
        return request

    def test_multiple_wraps_without_duplicates(self):
        for count in (10000, 60000, 110000, 160000, 210000):
            self.reader.sample(self.packet(count), count)
        self.assertEqual((self.directory / 'stream-console.bin').read_bytes(), self.data[:210000])
        self.assertTrue(self.reader.report()['complete'])

    def test_gap_and_inflight_overwrite_are_not_presented_as_complete(self):
        self.reader.sample(self.packet(1000), 1)
        self.reader.sample(self.packet(100000, writer=1, dropped=9), 2)
        records = [json.loads(line) for line in (self.directory / 'stream-console.jsonl').read_text().splitlines()]
        self.assertEqual(records[-1]['missing_bytes'], 100000 - 65536 + 1 - 16384)
        self.assertFalse(self.reader.report()['complete'])
        self.assertEqual(self.reader.report()['guest_dropped_bytes'], 9)
        output = (self.directory / 'stream-console.bin').read_bytes()
        self.assertNotIn(bytes([255]), output)
        self.assertTrue(output.endswith(b'9 bytes dropped by guest writer ...]\n'))

    def test_mismatched_kernel_and_backward_counter_are_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'UUID'):
            self.reader.sample(self.packet(1000, wrong_uuid=True), 1)
        self.reader.sample(self.packet(1000), 2)
        with self.assertRaisesRegex(RuntimeError, 'backwards'):
            self.reader.sample(self.packet(999), 3)


if __name__ == '__main__':
    unittest.main()
