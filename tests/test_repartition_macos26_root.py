# SPDX-License-Identifier: MIT
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from backup_device import parse_gpt
from create_log_partition import geometry
from repartition_macos26_root import BLOCK, WINDOW, apply, layout, sha


class RepartitionRoot(unittest.TestCase):
    def fixture(self, gib=100):
        lbas = gib * (1 << 30) // BLOCK
        entries = bytearray(4096)
        for index, name, first, last in ((0, 'persist', 6, 255), (28, 'userdata', 256, lbas - 6)):
            at = index * 128
            entries[at:at + 16] = uuid.UUID(int=index + 1).bytes_le
            entries[at + 16:at + 32] = uuid.UUID(int=index + 32).bytes_le
            struct.pack_into('<QQQ', entries, at + 32, first, last, 0x1234)
            entries[at + 56:at + 56 + len(name) * 2] = name.encode('utf-16-le')
        copies = []
        for current, other, table, start in ((1, lbas - 1, 2, 0),
                                            (lbas - 1, 1, lbas - 2, lbas - WINDOW // BLOCK)):
            data = bytearray(WINDOW)
            header = bytearray(BLOCK)
            struct.pack_into('<8sIIIIQQQQ16sQIII', header, 0, b'EFI PART', 0x10000, 92,
                             0, 0, current, other, 6, lbas - 6, uuid.UUID(int=101).bytes_le,
                             table, 32, 128, zlib.crc32(entries))
            struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))
            at = (current - start) * BLOCK
            data[at:at + BLOCK] = header
            at = (table - start) * BLOCK
            data[at:at + len(entries)] = entries
            copies.append(bytes(data))
        return *copies, lbas

    def test_only_userdata_end_and_new_root_entry_change(self):
        primary, secondary, lbas = self.fixture()
        outputs, plan = layout(primary, secondary, lbas, 64)
        before = geometry(primary, lbas, 0)
        after = geometry(outputs['primary'], lbas, 0)
        backup = geometry(outputs['secondary'], lbas, lbas - WINDOW // BLOCK)
        self.assertEqual(after[2], backup[2])
        self.assertEqual(before[2][:128], after[2][:128])
        self.assertEqual(before[2][28 * 128:28 * 128 + 40], after[2][28 * 128:28 * 128 + 40])
        self.assertEqual(before[2][28 * 128 + 48:29 * 128], after[2][28 * 128 + 48:29 * 128])
        changed = [i for i in range(32) if before[2][i * 128:(i + 1) * 128] != after[2][i * 128:(i + 1) * 128]]
        self.assertEqual(changed, [1, 28])
        self.assertEqual(plan['root_bytes'], 64 << 30)
        self.assertEqual(plan['root_first_lba'], plan['userdata_last_lba'] + 1)
        self.assertEqual(plan['root_first_lba'] % (WINDOW // BLOCK), 0)
        self.assertEqual(plan['root_last_lba'] - plan['root_first_lba'] + 1, (64 << 30) // BLOCK)
        self.assertEqual(after[1][56:72], before[1][56:72])
        parse_gpt(outputs['secondary'], BLOCK, lbas, lbas - WINDOW // BLOCK)

    def test_too_small_and_corrupt_inputs_are_refused(self):
        primary, secondary, lbas = self.fixture(70)
        with self.assertRaisesRegex(ValueError, 'smaller than'):
            layout(primary, secondary, lbas, 64)
        primary = bytearray(primary)
        primary[BLOCK + 16] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC'):
            layout(primary, secondary, lbas, 32)

    def test_stale_live_table_prevents_any_write(self):
        primary, secondary, lbas = self.fixture()
        outputs, plan = layout(primary, secondary, lbas, 64)
        plan.update(serial='29d9c0be', before=dict(primary=sha(primary), secondary=sha(secondary)))
        class Device:
            serial = '29d9c0be'
            def __init__(self):
                self.lbas = lbas
                self.writes = []
            def require_recovery(self):
                pass
            def read(self, start, count):
                changed = bytearray(primary)
                changed[0] ^= 1
                return bytes(changed) if start == 0 else secondary
            def write(self, *args):
                self.writes.append(args)
        device = Device()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'plan.json').write_text(json.dumps(plan))
            for kind, data in (('primary', primary), ('secondary', secondary)):
                (folder / f'before-{kind}.bin').write_bytes(data)
                (folder / f'after-{kind}.bin').write_bytes(outputs[kind])
            with self.assertRaisesRegex(ValueError, 'changed after'):
                apply(device, folder)
            self.assertFalse(device.writes)
            self.assertFalse((folder / 'apply.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
