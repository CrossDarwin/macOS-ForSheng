# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class NativeGopScanout(unittest.TestCase):
    def test_scaled_rows_preserve_pixel_order_and_destination_bounds(self):
        compiler = shutil.which('c++')
        if compiler is None:
            self.skipTest('requires a host C++ compiler')
        source = Path(__file__).with_name('native_gop_scanout.cpp')
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'scanout'
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', str(source), '-o', str(executable)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
