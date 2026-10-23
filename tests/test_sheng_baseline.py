# SPDX-License-Identifier: MIT
import hashlib
import json
from pathlib import Path
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ShengBaseline(unittest.TestCase):
    def test_complete_pinned_upstream_config_and_archive_chain(self):
        baseline = json.loads((ROOT / 'config/sheng-baseline.json').read_text())
        upstream = ROOT / 'UniXNU-sheng'
        if not upstream.is_dir():
            self.skipTest('fetch the locked core sources to verify upstream configuration drift')
        actual = (ROOT / 'config/sheng_defconfig').read_bytes()
        self.assertEqual(actual, (upstream / 'configs/sheng_defconfig').read_bytes())
        self.assertEqual(hashlib.sha256(actual).hexdigest(), baseline['defconfig_sha256'])
        board_data = (upstream / 'board.toml').read_bytes()
        self.assertEqual(hashlib.sha256(board_data).hexdigest(), baseline['board_sha256'])
        board = tomllib.loads(board_data.decode())
        self.assertEqual(baseline['archives'], board['kernel']['archives'])
        self.assertEqual(baseline['config_overrides'], {})
        self.assertEqual(baseline['archive_overrides'], [])
        for option in ('DT_PANIC_REGION', 'BOOT_PROGRESS', 'NATIVE_UFS', 'NATIVE_PAN', 'NATIVE_ARCH_TIMER'):
            self.assertIn(f'CONFIG_XNU_{option}=y'.encode(), actual.splitlines())
