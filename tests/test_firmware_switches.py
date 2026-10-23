# SPDX-License-Identifier: MIT
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
from unixnu.firmware import build_switches
from unixnu.util import Error


class FirmwareSwitches(unittest.TestCase):
    def test_opt_in_keeps_board_defaults(self):
        board = {'FD_BASE': '0xa7100000', 'DEVICE_MODEL': 'sheng'}
        self.assertEqual(build_switches(board, None), board)
        actual = build_switches(board, ['SHENG_PREFLIGHT_ONLY=1'])
        self.assertEqual(actual['SHENG_PREFLIGHT_ONLY'], '1')
        self.assertNotIn('SHENG_PREFLIGHT_ONLY', board)

    def test_geometry_and_malformed_switches_are_rejected(self):
        for value in ('FD_SIZE=0', 'FD_BASE=0', 'SHENG_PREFLIGHT_ONLY', '=1',
                      'SHENG_PREFLIGHT_ONLY=', 'SHENG_PREFLIGHT_ONLY=1 -D FD_SIZE=0',
                      'SHENG_PREFLIGHT_ONLY=1\nFD_SIZE=0', '../config=1'):
            with self.assertRaises(Error):
                build_switches({}, [value])


if __name__ == '__main__':
    unittest.main()
