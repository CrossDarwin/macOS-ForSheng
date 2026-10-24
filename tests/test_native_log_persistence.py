# SPDX-License-Identifier: MIT
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from capture_persistent_log import inspect_capture, request


class NativeLogPersistence(unittest.TestCase):
    def test_real_saver_with_mock_efi_services(self):
        clang = os.environ.get('CLANG', shutil.which('clang'))
        include = ROOT / 'uefi-sheng/Mu_Basecore/MdePkg/Include'
        if not clang or not (include / 'Uefi.h').is_file():
            self.skipTest('requires host clang and the pinned EDK2 headers')
        patch = (ROOT / 'patches/UniXNU/0015-native-retained-log-persistence.patch').read_text()
        addition = patch.split('+++ b/drivers/DarwinBoot/DarwinBootPkg/Driver/NativeLogSave.h\n', 1)[1]
        header = ''.join(line[1:] for line in addition.splitlines(keepends=True)
                         if line.startswith('+') and not line.startswith('+++'))
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / 'NativeLogSave.h').write_text(header)
            executable = work / 'saver'
            subprocess.run([clang, '-fshort-wchar', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-function', '-Wno-missing-field-initializers',
                            '-I' + str(include), '-I' + str(include / 'X64'), '-I' + str(work),
                            str(ROOT / 'tests/native_log_save_host.c'), '-o', str(executable)], check=True)
            volume = work / 'macoslog'
            volume.mkdir()
            subprocess.run([str(executable), str(volume)], check=True)
            for capture in ('CAP00001', 'CAP00002', 'CAP00005', 'CAP00006'):
                info = inspect_capture(volume / capture, '62626262-6262-6262-6262-626262626262')
                self.assertTrue(info['internal_file_capture'])
                self.assertFalse(info['warm_reboot_retention_qualified'])
            self.assertFalse(info['native']['complete'])
            self.assertEqual(info['native']['omitted_bytes'], 18081)
            for capture in ('CAP00003', 'CAP00004'):
                self.assertFalse((volume / capture / 'DONE.TXT').exists())
            raw = (volume / 'CAP00001/REQUEST.BIN').read_bytes()
            self.assertEqual(request(raw)['log_pa'], '0x881004000')
            with self.assertRaises(ValueError):
                request(raw[:-1])
            with self.assertRaises(ValueError):
                inspect_capture(volume / 'CAP00001', '00000000-0000-0000-0000-000000000001')


if __name__ == '__main__':
    unittest.main()
