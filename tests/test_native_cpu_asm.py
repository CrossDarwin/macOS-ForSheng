# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from native_cpu_asm import audit_sgi
from native_macho import macho


class NativeCpuAsm(unittest.TestCase):
    def test_macho_retains_the_real_sgi_write_and_probe_operands(self):
        compiler = os.environ.get('SHENG_TEST_CLANG') or shutil.which('clang')
        if not compiler:
            self.skipTest('Requires an AArch64-capable Clang')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in ('ArmCpu', 'ArmDTPlatform'):
                target = work / name
                target.mkdir()
                shutil.copy2(ROOT / 'UniXNU/drivers' / name / (name + '.cpp'), target)
            for patch in ('machine-driver-declarations.patch', 'machine-cpu-registration.patch',
                          'machine-cpu-interrupt-order.patch', 'machine-cpu-smp-bootstrap.patch',
                          'machine-cpu-inline-asm.patch'):
                subprocess.run(['git', 'apply', '--unsafe-paths', '--directory=' + directory,
                    str(ROOT / 'platform/sheng/macos26/patches' / patch)], check=True, capture_output=True)
            source = (work / 'ArmCpu/ArmCpu.cpp').read_text()
            statements = re.findall(r'__asm__ volatile \("([^"\n]*)"[^;]*;', source)
            self.assertFalse(any(';' in statement for statement in statements))
            send = next(line.strip() for line in source.splitlines()
                        if r'dsb ishst\n\tmsr icc_sgi1r_el1' in line)
            probe = next(line.strip() for line in source.splitlines()
                         if r'msr icc_sgi1r_el1' in line and '(tb)' in line)
            test = work / 'sgi.c'
            test.write_text('void send(unsigned long sgi) { ' + send + ' }\n'
                'unsigned long probe(unsigned long arg) { '
                'register unsigned long sgi __asm__("x9")=arg; '
                'register unsigned long tb __asm__("x10"); ' + probe + ' return tb; }\n'
                'void truncated(unsigned long sgi) { '
                '__asm__ volatile("dsb ishst; msr icc_sgi1r_el1, %0; isb" :: "r"(sgi) : "memory"); }\n')
            output = work / 'sgi.o'
            subprocess.run([compiler, '--target=arm64e-apple-macos26.5', '-ffreestanding',
                '-O2', '-c', str(test), '-o', str(output)], check=True, capture_output=True)
            audit_sgi(output, ('_send', '_probe'))
            with self.assertRaisesRegex(ValueError, 'Missing emitted'):
                audit_sgi(output, ('_truncated',))
            data = output.read_bytes()
            section = next(s for segment in macho(data)['segments'] for s in segment['sections']
                           if s['name'] == '__text')
            text = data[section['fileoff']:section['fileoff'] + section['size']]
            self.assertIn((0xd518cba9).to_bytes(4, 'little'), text)
            self.assertIn((0xd53be04a).to_bytes(4, 'little'), text)


if __name__ == '__main__':
    unittest.main()
