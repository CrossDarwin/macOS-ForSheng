# SPDX-License-Identifier: GPL-3.0-or-later
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from native_storage_module import validate_private_slot


class PrivateDisplaySlot(unittest.TestCase):
    def setUp(self):
        self.pointer = dict(authenticated=True, key=0, diversity=4202, address_diversity=True)
        self.allowed = [dict(slot=470, original=self.pointer, new_site=0x1000, new_target=0x2000)]
        self.item = dict(self.pointer, new_site=0x1000, new_target=0x2000)

    def test_exact_inherited_slot_is_admitted(self):
        self.assertEqual(validate_private_slot(self.item, self.allowed)['slot'], 470)

    def test_direct_call_other_slot_or_changed_pac_is_rejected(self):
        for field, value in dict(new_site=0x3000, new_target=0x4000, authenticated=False,
                                 key=1, diversity=0, address_diversity=False).items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_private_slot(self.item | {field: value}, self.allowed)

    def test_ambiguous_original_slot_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_private_slot(self.item, self.allowed + copy.deepcopy(self.allowed))
