# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class NativeProcessOutput(unittest.TestCase):
    def test_real_formatter_filters_faults_and_bounds_user_reads(self):
        compiler = shutil.which('cc')
        if compiler is None:
            self.skipTest('requires a host C compiler')
        source = Path(__file__).with_name('native_process_output.c')
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'process-output'
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', str(source), '-o', str(executable)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)
