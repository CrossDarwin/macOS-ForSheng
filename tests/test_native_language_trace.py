# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from native_language_trace import render, validate, verify_binary


class LanguageTrace(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / 'config/macos26-language-trace.json').read_text())

    def test_changed_instruction_or_identity_contract_is_rejected(self):
        validate(self.document)
        for key, value in [('boot_argument', 'trace=1'), ('default_off', False),
                           ('disk_writes', True), ('original_signature_validation_required', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(self.document | {key: value})
        for key, value in [('rva', 0xcbdc), ('destination', 16), ('tag', 0xc471),
                           ('instruction', 'd503201f')]:
            changed = copy.deepcopy(self.document)
            changed['points'][2][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(changed)
        with self.assertRaises(ValueError):
            verify_binary(self.document, bytes(0x40000))

    def test_kernel_handler_preserves_state_and_rejects_unrelated_traps(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('Requires a host C compiler')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            vm = work / 'vm'
            vm.mkdir()
            for source, target in [('ui_policy.h', 'sheng_recovery_ui.h'),
                                   ('language_trace.h', 'sheng_language_trace.h')]:
                (vm / target).symlink_to(ROOT / 'platform/sheng/macos26/recovery' / source)
            (vm / 'sheng_language_trace_pages.h').write_text(render(self.document))
            image = bytearray(0x40000)
            at = self.document['uuid_command_offset']
            image[at:at + 24] = bytes.fromhex(self.document['uuid_command'])
            (work / 'image.bin').write_bytes(image)
            command = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-I', str(work),
                       str(ROOT / 'tests/native_language_trace.c'), '-o', str(work / 'trace')]
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            subprocess.run([str(work / 'trace'), str(work / 'image.bin')],
                           check=True, capture_output=True, timeout=15)

    def test_replay_matches_original_arm64_instructions(self):
        try:
            from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
            from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X19,
                UC_ARM64_REG_X20, UC_ARM64_REG_X24, UC_ARM64_REG_PC, UC_ARM64_REG_NZCV)
        except ImportError:
            self.skipTest('Requires Unicorn for original instruction execution')
        registers = {19: UC_ARM64_REG_X19, 20: UC_ARM64_REG_X20, 24: UC_ARM64_REG_X24}
        for point in self.document['points']:
            for value in (0, 37, 0xffffffffffffffff):
                with self.subTest(site=point['name'], value=value):
                    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
                    cpu.mem_map(0x10000, 0x1000)
                    cpu.mem_write(0x10000, struct.pack('<I', int(point['instruction'], 16)))
                    cpu.reg_write(UC_ARM64_REG_X0, value)
                    cpu.reg_write(UC_ARM64_REG_NZCV, 0xa0000000)
                    cpu.emu_start(0x10000, 0x10004, count=1)
                    step = 20 if point['replay'] == 'cbnz_x0' and value else 4
                    self.assertEqual(cpu.reg_read(UC_ARM64_REG_PC), 0x10000 + step)
                    self.assertEqual(cpu.reg_read(UC_ARM64_REG_X0), value)
                    self.assertEqual(cpu.reg_read(UC_ARM64_REG_NZCV), 0xa0000000)
                    if point['replay'] == 'mov_x0':
                        self.assertEqual(cpu.reg_read(registers[point['destination']]), value)


if __name__ == '__main__':
    unittest.main()
