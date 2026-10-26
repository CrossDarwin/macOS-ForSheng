# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_macos26_gop import prepare


class PinnedDisplayInputs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'config').mkdir()
        (self.root / 'platform/sheng/macos26/display').mkdir(parents=True)
        (self.root / 'platform/sheng/macos26/display/gop_scanout.h').write_text('// scanout\n')
        (self.root / 'platform/sheng/macos26/display/gop_layers.h').write_text('// layers\n')
        self.output = self.root / 'output'
        inputs = self.output / 'inputs' / ('1' * 40)
        inputs.mkdir(parents=True)
        files = {}
        for name, data in (('DroidVMDisplay.cpp', b'// upstream\n'),
                           ('IOMobileFramebufferABI.h', b'// ABI\n')):
            (inputs / name).write_bytes(data)
            files[name] = dict(path='overlay/kext/DroidVMDisplay/' + name,
                              canonical_sha256=hashlib.sha256(data).hexdigest())
        self.manifest = dict(repository='Droid-VM/macOS-DroidVM', revision='1' * 40,
                             files=files, abi={'test': True})
        (self.root / 'config/macos26-gop-reference.json').write_text(json.dumps(self.manifest))
        (self.root / 'platform/sheng/macos26/display/0001-native-gop-display.patch').write_text(
            '--- a/DroidVMDisplay.cpp\n+++ b/DroidVMDisplay.cpp\n'
            '@@ -1 +1 @@\n-// upstream\n+// adapted\n')

    def test_cached_build_reapplies_to_pristine_input(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected download')):
            first = prepare(self.root, self.output)
            second = prepare(self.root, self.output)
        self.assertEqual(first, second)
        self.assertEqual((self.output / 'NativeGOPDisplay.cpp').read_text(), '// adapted\n')
        self.assertEqual((self.output / 'gop_scanout.h').read_text(), '// scanout\n')
        self.assertEqual(first['scanout_sha256'], hashlib.sha256(b'// scanout\n').hexdigest())
        self.assertEqual((self.output / 'gop_layers.h').read_text(), '// layers\n')
        self.assertEqual(first['layer_selection_sha256'], hashlib.sha256(b'// layers\n').hexdigest())

    def test_changed_source_or_header_is_rejected(self):
        for name in self.manifest['files']:
            with self.subTest(name=name):
                path = self.output / 'inputs' / self.manifest['revision'] / name
                original = path.read_bytes()
                path.write_bytes(original + b'// changed\n')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    prepare(self.root, self.output)
                path.write_bytes(original)

    def test_previous_revision_cache_is_not_reused(self):
        import io
        old_inputs = self.output / 'inputs'
        for name in self.manifest['files']:
            (old_inputs / name).write_bytes(b'// obsolete source\n')
        previous = self.manifest['revision']
        self.manifest['revision'] = '2' * 40
        (self.root / 'config/macos26-gop-reference.json').write_text(json.dumps(self.manifest))

        def download(url, timeout):
            self.assertIn('/' + self.manifest['revision'] + '/', url)
            return io.BytesIO((old_inputs / previous / url.rsplit('/', 1)[1]).read_bytes())

        with patch('urllib.request.urlopen', side_effect=download) as request:
            evidence = prepare(self.root, self.output)
        self.assertEqual(request.call_count, 2)
        self.assertIn(self.manifest['revision'], evidence['reference'])
        self.assertEqual((self.output / 'NativeGOPDisplay.cpp').read_text(), '// adapted\n')
        self.assertEqual((old_inputs / 'DroidVMDisplay.cpp').read_bytes(), b'// obsolete source\n')

    def test_patch_context_drift_is_not_accepted(self):
        path = self.root / 'platform/sheng/macos26/display/0001-native-gop-display.patch'
        path.write_text(path.read_text().replace('-// upstream', '-// other revision'))
        import subprocess
        with self.assertRaises(subprocess.CalledProcessError):
            prepare(self.root, self.output)
