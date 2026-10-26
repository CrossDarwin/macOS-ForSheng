# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from capture_boot_logs import decode_log


class BootLogs(unittest.TestCase):
    def test_short_ascii_with_large_zero_tail(self):
        text = 'Boot image header OS version == 0\r\n'
        self.assertEqual(decode_log(text.encode().ljust(65536, b'\0')), text)

    def test_utf16_with_large_zero_tail(self):
        text = 'LoadImageAndAuthVB2() status: Invalid Parameter\r\n'
        self.assertEqual(decode_log(text.encode('utf-16-le').ljust(65536, b'\0')), text)
