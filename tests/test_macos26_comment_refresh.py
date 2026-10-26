# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise comment-only patch migration without changing recorded code."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_macos26_xnu as build


class CommentRefresh(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = self.root / 'sources/macos26/xnu'
        self.base.mkdir(parents=True)
        self.git(self.base, 'init', '-q')
        self.git(self.base, 'config', 'user.name', 'Test')
        self.git(self.base, 'config', 'user.email', 'test@example.invalid')
        self.original = 'int value(void) { return 0; }\n'
        (self.base / 'value.c').write_text(self.original)
        (self.base / 'unchanged.h').write_text('#define UNCHANGED 1\n')
        self.git(self.base, 'add', '.')
        self.git(self.base, 'commit', '-qm', 'Base')
        self.active = self.root / 'active'
        self.git(self.root, 'clone', '-q', str(self.base), str(self.active))
        self.output = self.root / 'out'
        self.output.mkdir()
        self.patch_path = self.root / 'comments.patch'
        old = self.make_patch('/* Previous comment. */\nint value(void) { return 1; }\n')
        self.patch_path.write_bytes(old)
        self.git(self.active, 'apply', str(self.patch_path))
        self.applied = {'comments.patch': hashlib.sha256(old).hexdigest()}
        self.before = (self.active / 'value.c').read_bytes()

    @staticmethod
    def git(directory, *arguments):
        return subprocess.check_output(['git', '-C', str(directory), *arguments], stderr=subprocess.DEVNULL)

    def make_patch(self, content):
        (self.base / 'value.c').write_text(content)
        result = self.git(self.base, 'diff')
        (self.base / 'value.c').write_text(self.original)
        return result

    def refresh(self, content):
        self.patch_path.write_bytes(self.make_patch(content))
        with patch.multiple(build, ROOT=self.root, OUT=self.output, PATCHES=[self.patch_path]):
            build.refresh_comment_only_patches(self.active, self.applied)

    def test_comments_refresh_without_touching_unchanged_files(self):
        stamp = (self.active / 'unchanged.h').stat().st_mtime_ns
        wanted = '/* Updated English comment. */\nint value(void) { return 1; }\n'
        self.refresh(wanted)
        self.assertEqual((self.active / 'value.c').read_text(), wanted)
        self.assertEqual((self.active / 'unchanged.h').stat().st_mtime_ns, stamp)
        self.assertEqual(self.applied['comments.patch'], build.sha(self.patch_path))

    def test_code_or_string_changes_are_refused_before_writes(self):
        old_digest = dict(self.applied)
        for body in ('return 2;', 'return "/* Not a comment. */";'):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, 'beyond comments'):
                self.refresh('/* Updated comment. */\nint value(void) { ' + body + ' }\n')
            self.assertEqual((self.active / 'value.c').read_bytes(), self.before)
            self.assertEqual(self.applied, old_digest)


if __name__ == '__main__':
    unittest.main()
