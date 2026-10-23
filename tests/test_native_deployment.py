# SPDX-License-Identifier: MIT
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from boot_native_experiment import boot_once


class NativeDeployment(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'sheng-macos26-kernel.img').write_bytes(b'fixture')
        self.build = self.root / 'build.json'
        self.build.write_text(json.dumps(dict(temporary_ram_boot=True,
            partition_images_written=False, container_bytes=7, container_sha256='fixture')))
        self.output = self.root / 'record'

    def test_changed_slot_never_sends_image(self):
        with patch('boot_native_experiment.subprocess.run', return_value=
                   subprocess.CompletedProcess([], 0, '', 'current-slot: b\n')) as run:
            result = boot_once(self.build, 'device', 'a', self.output)
        self.assertEqual(result['status'], 'refused-slot-mismatch')
        self.assertEqual(result['boot_attempts'], 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][-2:], ['getvar', 'current-slot'])

    def test_unconfirmed_boot_is_not_retried(self):
        with patch('boot_native_experiment.subprocess.run', side_effect=[
            subprocess.CompletedProcess([], 0, '', 'current-slot: a\n'),
            subprocess.CompletedProcess([], 0, '', 'slot-unbootable:a: no\n'),
            subprocess.CompletedProcess([], 1, '', 'Status read failed (No such device)\n')
        ]) as run:
            result = boot_once(self.build, 'device', 'a', self.output)
        self.assertEqual(result['status'], 'boot-unconfirmed')
        self.assertEqual(run.call_count, 3)
        self.assertEqual(result['boot_attempts'], 1)
        self.assertFalse(result['kernel_execution_confirmed'])

    def test_timed_out_boot_is_not_retried(self):
        with patch('boot_native_experiment.subprocess.run', side_effect=[
            subprocess.CompletedProcess([], 0, '', 'current-slot: a\n'),
            subprocess.CompletedProcess([], 0, '', 'slot-unbootable:a: no\n'),
            subprocess.TimeoutExpired(['fastboot'], 90, output=b'Sending OKAY\n')
        ]) as run:
            result = boot_once(self.build, 'device', 'a', self.output)
        self.assertEqual(result['status'], 'boot-unconfirmed')
        self.assertEqual(run.call_count, 3)
        self.assertIn('Sending OKAY', (self.output / 'fastboot-boot.txt').read_text())

    def test_unbootable_current_slot_never_sends_image(self):
        with patch('boot_native_experiment.subprocess.run', side_effect=[
            subprocess.CompletedProcess([], 0, '', 'current-slot: a\n'),
            subprocess.CompletedProcess([], 0, '', 'slot-unbootable:a: yes\n')
        ]) as run:
            result = boot_once(self.build, 'device', 'a', self.output)
        self.assertEqual(result['status'], 'refused-slot-unbootable')
        self.assertEqual(result['boot_attempts'], 0)
        self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
