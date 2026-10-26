# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import shutil
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UfsRootPartition(unittest.TestCase):
    def test_production_parser_preserves_userdata_with_explicit_root_partition(self):
        compiler = os.environ.get('CXX') or shutil.which('clang++') or shutil.which('g++')
        source = ROOT / 'UniXNU/drivers/NativeUfs/tests/RootLayout.cpp'
        if not compiler or not source.exists():
            self.skipTest('requires pinned UFS parser and host C++ compiler')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            original = source.read_text().replace('#include "../RootDiagnostics.h"',
                '#include "' + str(source.parent.parent / 'RootDiagnostics.h') + '"')
            original = original.replace('#include "../RootLayout.h"',
                '#include "' + str(source.parent.parent / 'RootLayout.h') + '"')
            dedicated = original.replace('for(unsigned i=0;i<8;++i)entries[56+2*i]="userdata"[i];',
                'for(unsigned i=0;i<9;++i)entries[56+2*i]="macosroot"[i];')
            dedicated = dedicated.replace('  expect([]{},true,0);', '''  expect([]{},true,0);
  expect([]{ memset(entries+56,0,72);
    for(unsigned i=0;i<8;++i)entries[56+2*i]="userdata"[i]; },false,0);
  assert(reads==2);''')
            for name, text, definitions in (
                ('upstream', original, []),
                ('dedicated', dedicated, ['-DNATIVE_UFS_ROOT_PARTITION_NAME="macosroot"']),
            ):
                path = directory / (name + '.cpp')
                path.write_text(text)
                binary = directory / name
                subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                '-fsanitize=address,undefined', *definitions,
                                str(path), '-lcrypto', '-o', str(binary)],
                               check=True, timeout=60, capture_output=True)
                subprocess.run([str(binary)], check=True, timeout=20, capture_output=True)


if __name__ == '__main__':
    unittest.main()
