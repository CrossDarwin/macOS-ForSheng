# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from install_macos26_ufs_root import qualify_android_format


class AndroidFormat(unittest.TestCase):
    def test_only_the_rebuilt_bounded_userdata_can_qualify(self):
        plan = dict(root_unique_guid='test-root', userdata_bytes=168 << 30)
        evidence = dict(serial='test-device', read_only=True, root_partition_guid='test-root',
            userdata_partition_bytes=168 << 30, filesystem_bytes=(168 << 30) - (2 << 20),
            filesystem='f2fs', user_setup_complete='0', physical_partition='sda29', physical_disk='sda')
        qualify_android_format(evidence, plan, 'test-device')
        for key, value in [('filesystem_bytes', 232 << 30), ('physical_partition', 'sda30'),
                           ('physical_disk', 'sde'), ('user_setup_complete', '1'),
                           ('root_partition_guid', 'another-root'), ('read_only', False),
                           ('userdata_partition_bytes', 232 << 30), ('serial', 'another-device')]:
            with self.subTest(field=key), self.assertRaises(ValueError):
                qualify_android_format({**evidence, key: value}, plan, 'test-device')


if __name__ == '__main__':
    unittest.main()
