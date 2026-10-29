# SPDX-License-Identifier: GPL-3.0-or-later
import io
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEYS = [(3, 0, 2, crm, op2) for crm, op2 in
        ((1, 0), (1, 1), (1, 2), (1, 3), (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1))]


class NativeSmpKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from elftools.elf.elffile import ELFFile
            from unicorn import Uc
        except ImportError:
            raise unittest.SkipTest('Requires pyelftools and Unicorn')
        compiler = os.environ.get('SHENG_TEST_CLANG') or shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('Requires an AArch64-capable Clang and LLD')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            asm = work / 'keys.S'
            asm.write_text('#define EXT(x) x\n'
                '#include "smp_keys.h"\n.text\n.global start\nstart:\n'
                'SHENG_BOOTSTRAP_KERNEL_KEYS\n.global finish\nfinish:\nnop\n'
                '.global sign_pointer\nsign_pointer:\npacia x9, x10\n'
                '.global auth_pointer\nauth_pointer:\nautia x9, x10\n'
                '.global generic_sign\ngeneric_sign:\npacga x11, x12, x13\n'
                '#include "smp_keys_storage.h"\n')
            compiled = subprocess.run([compiler, '--target=aarch64-none-elf', '-march=armv8.3-a',
                '-fuse-ld=lld', '-nostdlib', '-Wl,--image-base=0,-Ttext=0x10000,-Tdata=0x20000,--entry=start',
                '-I', str(ROOT / 'platform/sheng/macos26/pac'), str(asm), '-o', str(work / 'keys')],
                capture_output=True, text=True, timeout=30)
            if compiled.returncode:
                raise RuntimeError(compiled.stderr)
            apple = subprocess.run([compiler, '--target=arm64e-apple-macos26.5', '-march=armv8.3-a',
                '-c', '-I', str(ROOT / 'platform/sheng/macos26/pac'), str(asm), '-o', str(work / 'keys.o')],
                capture_output=True, text=True, timeout=30)
            if apple.returncode:
                raise RuntimeError(apple.stderr)
            elf = ELFFile(io.BytesIO((work / 'keys').read_bytes()))
            cls.segments = [(s['p_vaddr'], s.data()) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
            cls.symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}

    def cpu(self, keys, secondary, bank=None):
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
        from unicorn.arm64_const import UC_CPU_ARM64_MAX, UC_ARM64_REG_X21
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        cpu.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
        # Model the EL1 PAC access already available at the firmware handoff.
        cpu.cpr_write(3, 4, 1, 1, 0, (1 << 31) | (3 << 40))
        cpu.cpr_write(3, 6, 1, 1, 0, 1 | (1 << 10) | (3 << 16))
        cpu.cpr_write(3, 0, 2, 0, 2, 16 | (16 << 16) | (2 << 30))
        sctlr = cpu.cpr_read(3, 0, 1, 0, 0)
        cpu.cpr_write(3, 0, 1, 0, 0, sctlr | (1 << 31) | (1 << 30) | (1 << 27) | (1 << 13))
        cpu.mem_map(0, 0x40000)
        for address, data in self.segments:
            cpu.mem_write(address, data)
        for register, value in zip(KEYS, keys):
            cpu.cpr_write(*register, value)
        cpu.reg_write(UC_ARM64_REG_X21, 0x30000 if secondary else 0)
        if bank is not None:
            cpu.mem_write(self.symbols['sheng_boot_pac_bank'], bank)
        return cpu

    def run_bootstrap(self, cpu):
        cpu.emu_start(self.symbols['start'], self.symbols['finish'], count=256)

    def read_keys(self, cpu):
        return [cpu.cpr_read(*register) for register in KEYS]

    def test_secondary_installs_the_boot_bank_before_cross_cpu_authentication(self):
        from unicorn.arm64_const import (UC_ARM64_REG_X9, UC_ARM64_REG_X10, UC_ARM64_REG_X11,
                                         UC_ARM64_REG_X12, UC_ARM64_REG_X13)
        keys = [0x123456789abcdef0 ^ (index << 32) for index in range(10)]
        boot = self.cpu(keys, False)
        self.run_bootstrap(boot)
        self.assertEqual(self.read_keys(boot), keys)
        bank = bytes(boot.mem_read(self.symbols['sheng_boot_pac_bank'], 88))
        self.assertEqual(struct.unpack_from('<10Q', bank), tuple(keys))
        self.assertEqual(struct.unpack_from('<I', bank, 80)[0], 1)
        secondary = self.cpu([value ^ 0xdeadbeef for value in keys], True, bank)
        self.run_bootstrap(secondary)
        self.assertEqual(self.read_keys(secondary), keys)
        self.assertEqual(bytes(secondary.mem_read(self.symbols['sheng_boot_pac_bank'], 88)), bank)
        boot.reg_write(UC_ARM64_REG_X9, 0x12340)
        boot.reg_write(UC_ARM64_REG_X10, 0x98760)
        boot.emu_start(self.symbols['sign_pointer'], self.symbols['sign_pointer'] + 4, count=1)
        signed = boot.reg_read(UC_ARM64_REG_X9)
        self.assertNotEqual(signed, 0x12340)
        wrong_keys = self.cpu([value ^ 0xdeadbeef for value in keys], True, bank)
        wrong_keys.reg_write(UC_ARM64_REG_X9, signed)
        wrong_keys.reg_write(UC_ARM64_REG_X10, 0x98760)
        wrong_keys.emu_start(self.symbols['auth_pointer'], self.symbols['auth_pointer'] + 4, count=1)
        self.assertNotEqual(wrong_keys.reg_read(UC_ARM64_REG_X9), 0x12340)
        secondary.reg_write(UC_ARM64_REG_X9, signed)
        secondary.reg_write(UC_ARM64_REG_X10, 0x98760)
        secondary.emu_start(self.symbols['auth_pointer'], self.symbols['auth_pointer'] + 4, count=1)
        self.assertEqual(secondary.reg_read(UC_ARM64_REG_X9), 0x12340)
        signatures = []
        for cpu in (boot, secondary):
            cpu.reg_write(UC_ARM64_REG_X12, 0x12345)
            cpu.reg_write(UC_ARM64_REG_X13, 0x53480001)
            cpu.emu_start(self.symbols['generic_sign'], self.symbols['generic_sign'] + 4, count=1)
            signatures.append(cpu.reg_read(UC_ARM64_REG_X11))
        self.assertEqual(signatures[0], signatures[1])
        self.assertNotEqual(signatures[0], 0)

    def test_unpublished_bank_stops_without_replacing_secondary_keys(self):
        from unicorn import UcError
        from unicorn.arm64_const import UC_ARM64_REG_PC
        keys = list(range(10, 20))
        cpu = self.cpu(keys, True)
        with self.assertRaises(UcError):
            self.run_bootstrap(cpu)
        pc = cpu.reg_read(UC_ARM64_REG_PC)
        self.assertEqual(bytes(cpu.mem_read(pc, 4)), struct.pack('<I', 0xd4200000 | 0x534a << 5))
        self.assertEqual(self.read_keys(cpu), keys)


if __name__ == '__main__':
    unittest.main()
