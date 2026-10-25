# SPDX-License-Identifier: MIT
"""Keep root updates confined to ISC, with the new manifest committed last."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_macos26_ufs_windows as updater
from prepare_macos26_ufs_root import prepare, MIB
from repartition_macos26_root import BLOCK, WINDOW, layout
import test_repartition_macos26_root as partition_fixture


class UpdateWindows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.plan_dir, self.previous, self.candidate = [self.folder / n for n in ('plan', 'old', 'new')]
        self.plan_dir.mkdir()
        self.candidate.mkdir()
        primary, secondary, lbas = partition_fixture.RepartitionRoot().fixture()
        copies, self.plan = layout(primary, secondary, lbas, 64)
        self.plan.update(applied=True, gpt_readback_verified=True, serial='29d9c0be')
        for name, data in copies.items():
            (self.plan_dir / f'after-{name}.bin').write_bytes(data)
        source, evidence = self.folder / 'root.raw', self.folder / 'root.json'
        source.write_bytes(b'R' * 512)
        root_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        evidence.write_text(json.dumps(dict(build='25F71', bytes=512, sha256=root_hash, read_only_qemu_input=True)))
        self.old = prepare(source, evidence, self.previous)
        self.isc = b'I' * MIB
        self.contract = dict(bytes=512, sha256=root_hash, isc=dict(bytes=MIB, sha256=hashlib.sha256(self.isc).hexdigest()))
        config = self.folder / 'config'
        config.mkdir()
        (config / 'macos26-recovery-root.json').write_text(json.dumps(self.contract))
        self.new = dict(self.old, image_bytes=3*MIB, isc_volatile_overlay=True,
            windows=self.old['windows']+[dict(name='ISC', offset=2*MIB, bytes=MIB, sha256=self.contract['isc']['sha256'])])
        header = bytearray(BLOCK)
        header[:8] = b'SHNGROOT'
        struct.pack_into('<IIQ', header, 8, 1, 2, 3*MIB)
        for i, window in enumerate(self.new['windows']):
            struct.pack_into('<32sQQII32s40s', header, 24+i*128, window['name'].encode(), window['offset'],
                window['bytes'], 512, 1, bytes.fromhex(window['sha256']), bytes(40))
        header[4064:] = hashlib.sha256(header[:4064]).digest()
        self.new['manifest_sha256'] = hashlib.sha256(header).hexdigest()
        data = bytearray(3*MIB)
        data[:BLOCK] = header
        data[MIB:MIB+512] = source.read_bytes()
        data[2*MIB:] = self.isc
        (self.candidate / 'macosroot.img').write_bytes(data)
        (self.candidate / 'manifest.bin').write_bytes(header)
        (self.candidate / 'build.json').write_text(json.dumps(self.new))
        self.current = bytearray((self.previous / 'macosroot.img').read_bytes())+bytearray(MIB)
        old_digest = hashlib.sha256(self.current[:2*MIB]).hexdigest()
        self.plan['root_image_sha256'] = old_digest
        (self.plan_dir / 'plan.json').write_text(json.dumps(self.plan))
        self.installed = self.folder / 'installed.json'
        self.installed.write_text(json.dumps(dict(status='verified', readback_verified=True,
            destination=updater.PARTITION, destination_guid=self.plan['root_unique_guid'],
            sha256=old_digest, readback_sha256=old_digest)))
        owner = self
        class Device:
            serial, adb = '29d9c0be', ['adb', '-s', '29d9c0be']
            def __init__(self):
                self.lbas, self.fail_isc_hash, self.commands = lbas, False, []
            def require_recovery(self):
                pass
            def read(self, start, count):
                if start == owner.plan['root_first_lba']:
                    assert count == 1
                    return bytes(owner.current[:BLOCK])
                return copies['primary' if start == 0 else 'secondary']
            def shell(self, command, **kwargs):
                self.commands.append(command)
                if command.startswith('readlink'):
                    return '/dev/block/sda'+str(owner.plan['root_index'])
                if command.startswith('blockdev --getsize64'):
                    return str(owner.plan['root_bytes'])
                if 'sha256sum' in command:
                    if 'skip=1048576 count=512 ' in command:
                        data = owner.current[MIB:MIB+512]
                    elif 'skip=2097152 ' in command:
                        if self.fail_isc_hash:
                            return '0'*64+'  -'
                        data = owner.current[2*MIB:]
                    else:
                        data = owner.current
                    return hashlib.sha256(data).hexdigest()+'  -'
                return ''
        self.device = Device()
        self.writes = []

    def remote_write(self, arguments, **kwargs):
        command = arguments[-1]
        self.assertIn('of='+updater.PARTITION, command)
        self.assertIn('iflag=count_bytes', command)
        self.assertNotIn('blkdiscard', command)
        if 'seek=2 ' in command:
            self.writes.append('ISC')
            self.current[2*MIB:] = kwargs['stdin'].read(MIB)
        else:
            self.writes.append('manifest')
            self.current[:BLOCK] = kwargs['input']

    def run_update(self):
        with patch.object(updater, 'ROOT', self.folder), patch.object(updater.subprocess, 'run', side_effect=self.remote_write):
            return updater.update(self.device, self.plan_dir, self.previous, self.installed, self.candidate, self.folder/'deployment')

    def test_commits_manifest_after_isc_and_preserves_base_system(self):
        before = bytes(self.current[MIB:2*MIB])
        record = self.run_update()
        self.assertEqual(self.writes, ['ISC', 'manifest'])
        self.assertEqual(self.current[MIB:2*MIB], before)
        self.assertTrue(record['readback_verified'])
        self.assertTrue(record['manifest_committed'])
        self.assertFalse(record['base_system_written'])

    def test_bad_isc_readback_keeps_original_manifest_without_retry(self):
        header = bytes(self.current[:BLOCK])
        self.device.fail_isc_hash = True
        with self.assertRaisesRegex(ValueError, 'original manifest retained'):
            self.run_update()
        self.assertEqual(self.writes, ['ISC'])
        self.assertEqual(self.current[:BLOCK], header)
        record = json.loads((self.folder/'deployment/deployment.json').read_text())
        self.assertFalse(record['manifest_committed'])
        self.assertEqual(record['image_write_attempts'], 1)

    def test_overlapping_or_foreign_seed_is_refused(self):
        for key, value in (('offset', MIB), ('bytes', MIB*2), ('sha256', '0'*64)):
            candidate = copy.deepcopy(self.new)
            candidate['windows'][1][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'ISC extent'):
                updater.validate_update(self.old, candidate, self.plan, self.contract)

    def test_unknown_manifest_ack_is_recorded_without_retry(self):
        write = self.remote_write
        def disconnected(arguments, **kwargs):
            write(arguments, **kwargs)
            if 'input' in kwargs:
                raise subprocess.TimeoutExpired(arguments, 30)
        with patch.object(updater, 'ROOT', self.folder), patch.object(updater.subprocess, 'run', side_effect=disconnected):
            with self.assertRaises(subprocess.TimeoutExpired):
                updater.update(self.device, self.plan_dir, self.previous, self.installed,
                               self.candidate, self.folder/'deployment')
        record = json.loads((self.folder/'deployment/deployment.json').read_text())
        self.assertEqual(self.writes, ['ISC', 'manifest'])
        self.assertIsNone(record['manifest_committed'])
        self.assertEqual(record['failed_phase'], 'committing-manifest')

    def test_modified_candidate_payload_is_refused_before_writes(self):
        image = self.candidate/'macosroot.img'
        with image.open('r+b') as stream:
            stream.seek(2*MIB)
            stream.write(b'!')
        with self.assertRaisesRegex(ValueError, 'candidate payload'):
            self.run_update()
        self.assertEqual(self.writes, [])


if __name__ == '__main__':
    unittest.main()
