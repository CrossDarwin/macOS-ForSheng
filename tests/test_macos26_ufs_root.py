# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_macos26_ufs_root import prepare, MIB


class UfsRoot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / 'original.raw'
        self.original = bytes(range(256)) * 34
        self.source.write_bytes(self.original)
        self.evidence = self.directory / 'original.json'
        self.record = dict(build='25F71', bytes=len(self.original),
                           sha256=hashlib.sha256(self.original).hexdigest(), read_only_qemu_input=True)
        self.evidence.write_text(json.dumps(self.record))
        self.output = self.directory / 'output'

    def test_original_bytes_and_manifest_contract(self):
        report = prepare(self.source, self.evidence, self.output)
        header = (self.output / 'manifest.bin').read_bytes()
        image = (self.output / 'macosroot.img').read_bytes()
        self.assertEqual(header[:8], b'SHNGROOT')
        self.assertEqual(struct.unpack_from('<IIQ', header, 8), (1, 1, 2 * MIB))
        self.assertEqual(struct.unpack_from('<32sQQII32s40s', header, 24),
                         (b'OS' + bytes(30), MIB, len(self.original), 512, 1,
                          hashlib.sha256(self.original).digest(), bytes(40)))
        self.assertEqual(header[4064:], hashlib.sha256(header[:4064]).digest())
        self.assertEqual(image[:4096], header)
        self.assertEqual(image[MIB:MIB + len(self.original)], self.original)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(report['partition_writes_performed'])
        with self.assertRaises(FileExistsError):
            prepare(self.source, self.evidence, self.output)

    def test_wrong_paired_content_leaves_no_candidate(self):
        self.record['sha256'] = '00' * 32
        self.evidence.write_text(json.dumps(self.record))
        with self.assertRaisesRegex(ValueError, 'differs'):
            prepare(self.source, self.evidence, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
