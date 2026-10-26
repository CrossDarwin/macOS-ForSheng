# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from native_recovery_ui import PAGE, render, validate, verify_page


class RecoveryUiPolicy(unittest.TestCase):
    def setUp(self):
        self.original = bytes((n * 17 + n // 64) % 256 for n in range(PAGE))
        after = bytearray(self.original)
        after[12:16] = b'\x00\x00\x80\xd2'
        self.rule = dict(file='fixture', file_offset=PAGE,
                         before_sha256=hashlib.sha256(self.original).hexdigest(),
                         after_sha256=hashlib.sha256(after).hexdigest(),
                         edits=[dict(offset=12, before=self.original[12:16].hex(), after=after[12:16].hex())])
        self.document = dict(schema='sheng-recovery-ui-pages-v1', build='25F71', architecture='arm64e',
                             default_off=True, disk_writes=False, authentication_success_fabricated=False,
                             pages=[self.rule])

    def test_wrong_image_or_instruction_cannot_be_applied(self):
        validate(self.document)
        self.assertEqual(verify_page(self.original, self.rule)[12:16], b'\x00\x00\x80\xd2')
        for original in (self.original[:-1], bytes(PAGE)):
            with self.assertRaises(ValueError):
                verify_page(original, self.rule)
        invalid = copy.deepcopy(self.rule)
        invalid['edits'][0]['before'] = '00000000'
        with self.assertRaises(ValueError):
            verify_page(self.original, invalid)

    def test_extent_overlap_duplicate_and_contract_fail_closed(self):
        for field, value in dict(default_off=False, disk_writes=True, build='26A428',
                                 architecture='arm64', authentication_success_fabricated=True).items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(self.document | {field: value})
        for field, value in [('file', '../fixture'), ('file_offset', 1), ('file_offset', -PAGE),
                             ('before_sha256', 'invalid'), ('after_sha256', self.rule['before_sha256']),
                             ('edits', self.rule['edits'] * 2)]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(self.document | dict(pages=[self.rule | {field: value}]))
        with self.assertRaises(ValueError):
            validate(self.document | dict(pages=[self.rule] * 2))

    def test_pinned_manifest_is_bounded_and_default_off(self):
        document = json.loads((ROOT / 'config/macos26-recovery-ui-pages.json').read_text())
        self.assertEqual(len(validate(document)), 10)
        self.assertEqual(sum(len(p['edits']) for p in document['pages']), 12)

    def test_actual_c_engine_refuses_partial_writes_and_is_idempotent(self):
        compiler = shutil.which('cc')
        pkg = shutil.which('pkg-config')
        if not compiler or not pkg:
            self.skipTest('Requires a C compiler and OpenSSL development package')
        flags = subprocess.run([pkg, '--cflags', '--libs', 'openssl'], capture_output=True, text=True)
        if flags.returncode:
            self.skipTest('Requires an OpenSSL development package')
        import shlex
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'sheng_recovery_ui_pages.h').write_text(render(self.document))
            (target / 'page.bin').write_bytes(self.original)
            executable = target / 'policy'
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-I', str(target),
                            str(ROOT / 'tests/native_recovery_ui.c'), '-o', str(executable),
                            *shlex.split(flags.stdout)], check=True, capture_output=True, timeout=30)
            subprocess.run([str(executable), '0', str(target / 'page.bin')],
                           check=True, capture_output=True, timeout=15)


if __name__ == '__main__':
    unittest.main()
