# SPDX-License-Identifier: MIT
"""Exercise the production sparse ISC overlay against an immutable disk seed."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IscOverlay(unittest.TestCase):
    def test_partial_io_capacity_errors_and_immutable_seed(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            self.skipTest('requires a host C++ compiler')
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'overlay'
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', str(ROOT / 'tests/ufs_isc_overlay.cpp'),
                            '-o', str(executable)], check=True, capture_output=True, timeout=30)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
