# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeBootProgress(unittest.TestCase):
    def test_repeated_output_restarts_and_missing_stages_do_not_fake_progress(self):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('requires a C compiler')
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'progress'
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', str(ROOT / 'tests/native_boot_progress.c'),
                '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True, timeout=15)


if __name__ == '__main__':
    unittest.main()
