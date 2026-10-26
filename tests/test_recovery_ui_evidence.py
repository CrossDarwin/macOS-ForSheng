# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from recovery_ui_evidence import language_pixels, qualify_language_selector


class RecoveryUiEvidence(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.build = self.folder / 'build'
        self.build.mkdir()
        self.fixture = self.folder / 'fixture'
        self.fixture.mkdir()
        self.identity = dict(uuid='candidate', kernel_sha256='candidate-hash')
        sha = lambda path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        self.policy = dict(default_off=True, disk_writes=False, original_signature_validation_required=True,
            manifest_sha256=sha('config/macos26-recovery-ui-pages.json'),
            engine_sha256=sha('platform/sheng/macos26/recovery/ui_policy.h'),
            kernel_hook_sha256=sha('platform/sheng/macos26/recovery/ui_policy_kernel.h'))
        reference = json.loads((ROOT / 'config/macos26-gop-reference.json').read_text())
        display = dict(default_off=True, gpu_acceleration=False, publishes_vm_identity=False, required_cpus=1,
            reference='https://github.com/' + reference['repository'] + '/tree/' + reference['revision'],
            input_sha256={k: v['canonical_sha256'] for k, v in reference['files'].items()},
            patch_sha256=sha('platform/sheng/macos26/display/0001-native-gop-display.patch'),
            scanout_sha256=sha('platform/sheng/macos26/display/gop_scanout.h'),
            layer_selection_sha256=sha('platform/sheng/macos26/display/gop_layers.h'))
        self.save(self.build, 'build.json', dict(recovery_ui_policy=self.policy))
        self.save(self.build, 'security-relink.json', dict(storage_driver=dict(build=dict(native_gop_display=display))))
        self.save(self.fixture, 'qualification-inputs.json', dict(kernel=self.identity, compiled_policy=self.policy))
        self.save(self.fixture, 'gdb-stop.json', dict(kernel_sha256=self.identity['kernel_sha256']))
        self.audit = dict(debugger_user_memory_writes=0, debugger_user_pc_writes=0,
                          original_base_system_readonly=True, policy_controller_loaded=False)
        self.save(self.fixture, 'debugger-write-audit.json', self.audit)
        count = len(json.loads((ROOT / 'config/macos26-recovery-ui-pages.json').read_text())['pages'])
        self.geometry = dict(guest_memory_modified=False, guest_registers_modified=False,
            native_ui_policy=dict(_sheng_recovery_ui_enabled=1, _sheng_recovery_ui_pages_applied=count,
                                  _sheng_recovery_ui_page_mask=(1 << count) - 1),
            native_gop_geometry=dict(completed_frames=1, display_width=800, display_height=600))
        self.save(self.fixture, 'qmp-springboard-transition.json', self.geometry)
        self.state = dict(read_only=True, process=dict(name='Language Chooser'), selected_language_constant_text='zh-Hans', state_machine=6)
        self.save(self.fixture, 'after-chinese-click-2-state.json', self.state)
        self.save(self.fixture, 'continue-followup-state.json', dict(self.state, state_machine=4))
        for name in ('simplified-chinese-click-2.json', 'continue-after-chinese.json'):
            self.save(self.fixture, name, dict(events_submitted=True, guest_memory_modified=False,
                guest_registers_modified=False, device=dict(absolute=True)))
        samples = [dict(file=f'sample-{i}.png') for i in range(6)]
        for sample in samples:
            (self.fixture / sample['file']).write_bytes(b'unit-test-pixel-source')
        self.save(self.fixture, 'language-window-visibility-series.json', dict(read_only=True, samples=samples))

    @staticmethod
    def save(folder, name, record):
        (folder / name).write_text(json.dumps(record))

    def qualify(self):
        with patch('recovery_ui_evidence.language_pixels', return_value=dict(
                selected_row_blue_pixels=2000, title_light_pixels=600, language_rows_light_pixels=2000)):
            return qualify_language_selector(self.build, self.fixture, self.identity)

    def test_selector_acceptance_does_not_claim_tools_or_physical_input(self):
        actual = self.qualify()
        self.assertTrue(actual['real_continue_processed'])
        self.assertFalse(actual['recovery_tools_window_qualified'])
        self.assertFalse(actual['physical_display_qualified'])
        self.assertFalse(actual['physical_input_qualified'])

    def test_debugger_edits_and_stale_kernel_are_rejected(self):
        self.audit['debugger_user_memory_writes'] = 1
        self.save(self.fixture, 'debugger-write-audit.json', self.audit)
        with self.assertRaisesRegex(ValueError, 'audited native UI'):
            self.qualify()
        self.audit['debugger_user_memory_writes'] = 0
        self.save(self.fixture, 'debugger-write-audit.json', self.audit)
        self.save(self.fixture, 'gdb-stop.json', dict(kernel_sha256='stale'))
        with self.assertRaisesRegex(ValueError, 'packaged kernel'):
            self.qualify()

    def test_input_submission_alone_does_not_qualify(self):
        self.save(self.fixture, 'continue-followup-state.json', self.state)
        with self.assertRaisesRegex(ValueError, 'Continue state transition'):
            self.qualify()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'requires ffmpeg for QMP image decoding')
    def test_blank_frame_does_not_gain_visibility_from_reported_counts(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        path = self.fixture / 'blank.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>II5B', 800, 600, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes((800 * 3 + 1) * 600))) + chunk(b'IEND', b''))
        self.assertEqual(set(language_pixels(path).values()), {0})
        samples = [dict(file=f'sample-{i}.png') for i in range(6)]
        for sample in samples:
            shutil.copyfile(path, self.fixture / sample['file'])
        with self.assertRaisesRegex(ValueError, 'title, list or selected row is absent'):
            qualify_language_selector(self.build, self.fixture, self.identity)


if __name__ == '__main__':
    unittest.main()
