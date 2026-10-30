# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class FramebufferOwner(unittest.TestCase):
    def test_eight_writers_and_faulted_gui_lease(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('requires a C++ compiler')
        with tempfile.TemporaryDirectory() as temporary:
            binary = str(Path(temporary) / 'owner')
            subprocess.run([compiler, '-std=c++17', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror',
                str(Path(__file__).with_name('native_framebuffer_owner.cpp')), '-o', binary], check=True, timeout=30)
            subprocess.run([binary], check=True, timeout=15)
