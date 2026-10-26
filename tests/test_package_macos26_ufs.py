# SPDX-License-Identifier: GPL-3.0-or-later
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_macos26_ufs import qualify, qualify_development_dyld, qualify_isc_overlay, qualify_boot_progress
from build_macos26_storage import PROTOCOL_CHARACTERISTICS


class UfsPackage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.paths = [self.folder / name for name in ('build', 'observed', 'bootstrap', 'off')]
        for path in self.paths:
            path.mkdir()
        self.recovery = json.loads((ROOT / 'config/macos26-recovery-root.json').read_text())
        self.identity = dict(kernel_sha256='kernel', uuid='uuid')
        self.observed = dict(self.identity, reached=True, checkpoint='IOFindBSDRoot',
            source_crypto_initialized=True, bootstrap_diagnostic_disarmed=True,
            observed_globals=dict(_sheng_panel_ready='0x1', _sheng_panel_witness='0x1', _sheng_console_rows='0x18', _sheng_panel_bound_rows='0x18', _sheng_panic_panel_bound_rows='0x10'),
            original_component_interfaces={n: dict(registered=True, within_original_module=True)
                for n in ('_g_crypto_funcs', '_img4if', '_amfi', '_libCoreEntitlements', '_pthread_functions')})
        self.bootstrap = dict(self.identity, reached_c_entry=True, instruction_and_args_match=True,
            bootstrap_stage='0xf', post_mmu_framebuffer_mapping_ready=True,
            actual_stage_pixels=['0xff00ff00'] * 16)
        self.driver = dict(bundle='org.blu-sharky.NativeUfs',
            build=dict(root_partition='macosroot', root_lun=0, android_userdata_used=False,
                       recovery_root=self.recovery, recovery_transport_is_not_authentication=True),
            vtable_abi=dict(block_class='NativeUfsBlock', pac_metadata_matches=True, slots=326),
            symbols={name: index for index, name in enumerate(('_native_ufs_probe_requested',
                '_native_ufs_mapped', '_native_ufs_root_step', '_native_ufs_blocks_published'))})
        self.driver['build']['recovery_disk_image_protocol'] = dict(PROTOCOL_CHARACTERISTICS)
        self.off = dict(kernel_sha256='kernel', function_return_stack_matched=True, x0='0x0',
                        memory={f'{i:x}:4': '00000000' for i in range(4)})
        self.media = dict(status='verified', readback_verified=True, destination='/dev/block/by-name/macosroot',
                          destination_guid='guid', sha256='disk', readback_sha256='disk', bytes=2048)
        self.plan = dict(root_unique_guid='guid', applied=True, root_image_readback_verified=True,
                         root_image_sha256='disk', root_bytes=64 << 30)
        self.root = dict(image_bytes=2048, build='25F71', windows=[dict(name='OS',
                         bytes=self.recovery['bytes'], sha256=self.recovery['sha256'])])

    def run_qualification(self, *, with_isc=False):
        for path, record in ((self.paths[1] / 'result.json', self.observed),
                             (self.paths[2] / 'result.json', self.bootstrap),
                             (self.paths[3] / 'gdb-stop.json', self.off),
                             (self.paths[0] / 'security-relink.json', dict(candidate_sha256='kernel', storage_driver=self.driver)),
                             (self.folder / 'installed.json', self.media),
                             (self.folder / 'plan.json', self.plan),
                             (self.folder / 'root.json', self.root)):
            path.write_text(json.dumps(record))
        panels = [ROOT / 'platform/sheng/macos26/patches' / name for name in
                  ('0051-native-multiline-panic-panel.patch', '0052-native-independent-panic-surface.patch')]
        (self.paths[0] / 'build.json').write_text(json.dumps(dict(patches={
            str(panel.relative_to(ROOT)): hashlib.sha256(panel.read_bytes()).hexdigest() for panel in panels})))
        with patch('package_macos26_ufs.identify', return_value=(Path('kernel'), {}, self.identity)):
            return qualify(*self.paths, *(self.folder / name for name in ('installed.json', 'plan.json', 'root.json')), with_isc=with_isc)

    def test_isc_requires_current_compiled_overlay_and_disjoint_seed(self):
        self.root['windows'][0]['offset'] = 1 << 20
        isc = dict(name='ISC', offset=2 << 30, bytes=self.recovery['isc']['bytes'],
                   sha256=self.recovery['isc']['sha256'])
        self.root['windows'].append(isc)
        self.root.update(isc_volatile_overlay=True, image_bytes=isc['offset'] + isc['bytes'])
        self.media['bytes'] = self.root['image_bytes']
        overlay = dict(seed_read_only=True, disk_writes=False, persistent=False, limit_bytes=64 << 20,
            production_header_sha256=hashlib.sha256((ROOT / 'UniXNU/drivers/NativeUfs/RootWindowOverlay.h').read_bytes()).hexdigest(),
            sparse_disk_header_sha256=hashlib.sha256((ROOT / 'UniXNU/drivers/NativeRamBlock/SparseDisk.h').read_bytes()).hexdigest())
        self.driver['build']['isc_volatile_overlay'] = overlay
        self.assertEqual(self.run_qualification(with_isc=True)[2], self.identity)
        for field, value in (('persistent', True), ('disk_writes', True),
                             ('production_header_sha256', 'stale'), ('sparse_disk_header_sha256', 'stale')):
            original = overlay[field]
            overlay[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'isolated ISC'):
                self.run_qualification(with_isc=True)
            overlay[field] = original
        isc['offset'] = self.root['image_bytes']
        with self.assertRaisesRegex(ValueError, 'isolated ISC'):
            self.run_qualification(with_isc=True)

    def test_matching_recovery_transport_is_required(self):
        self.assertEqual(self.run_qualification()[2], self.identity)
        del self.driver['build']['recovery_root']
        with self.assertRaisesRegex(ValueError, 'recovery UFS ABI'):
            self.run_qualification()

    def test_stale_observation_and_active_hardware_are_refused(self):
        self.observed['kernel_sha256'] = 'other'
        with self.assertRaisesRegex(ValueError, 'exact native kernel'):
            self.run_qualification()
        self.observed['kernel_sha256'] = 'kernel'
        self.off['memory']['1:4'] = '01000000'
        with self.assertRaisesRegex(ValueError, 'touched hardware'):
            self.run_qualification()

    def test_computed_rows_do_not_qualify_a_six_row_binding(self):
        self.observed['observed_globals']['_sheng_panel_bound_rows'] = '0x6'
        with self.assertRaisesRegex(ValueError, 'exact native kernel'):
            self.run_qualification()

    def test_smaller_qemu_screen_uses_the_actual_computed_binding(self):
        self.observed['observed_globals']['_sheng_console_rows'] = '0x11'
        self.observed['observed_globals']['_sheng_panel_bound_rows'] = '0x11'
        self.assertEqual(self.run_qualification()[2], self.identity)

    def test_unmapped_panic_surface_is_refused(self):
        del self.observed['observed_globals']['_sheng_panic_panel_bound_rows']
        with self.assertRaisesRegex(ValueError, 'exact native kernel'):
            self.run_qualification()

    def test_wrong_partition_or_root_content_is_refused(self):
        self.media['destination'] = '/dev/block/by-name/userdata'
        with self.assertRaisesRegex(ValueError, 'dedicated root'):
            self.run_qualification()
        self.media['destination'] = '/dev/block/by-name/macosroot'
        self.root['windows'][0]['sha256'] = 'other'
        with self.assertRaisesRegex(ValueError, 'dedicated root'):
            self.run_qualification()


class DevelopmentDyldPackage(unittest.TestCase):
    def test_progress_requires_compiled_model_and_real_service_hooks(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            sha = lambda path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            record = dict(boot_progress=dict(default_off=True, stage_count=10, required_cpus=1,
                repeated_events_advance=False, stalled_is_not_deadlock=True,
                model_sha256=sha('platform/sheng/macos26/log/boot_progress.h'),
                kernel_sha256=sha('platform/sheng/macos26/log/boot_progress_kernel.h')),
                process_output_log=dict(default_off=True, vector_writes=True, max_bytes_per_write=159, max_iovecs=16,
                    source_sha256=sha('platform/sheng/macos26/log/process_output.h')),
                retained_log_source_sha256=sha('platform/sheng/macos26/log/retained_log.h'),
                patches={'platform/sheng/macos26/patches/' + name: sha('platform/sheng/macos26/patches/' + name)
                    for name in ('0055-native-process-output-log.patch', '0056-native-boot-progress.patch',
                                 '0057-native-vector-output-log.patch', '0058-native-progress-clock-ready.patch')})
            path = folder / 'build.json'
            path.write_text(json.dumps(record))
            self.assertFalse(qualify_boot_progress(folder)['physical_qualified'])
            record['boot_progress']['model_sha256'] = 'stale'
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, 'source differs'):
                qualify_boot_progress(folder)

    def test_wrapped_mount_lines_require_same_snapshot_stream_accounting(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            identity = dict(uuid='candidate', kernel_sha256='candidate-hash')
            names = json.loads((ROOT / 'config/macos26-recovery-root.json').read_text())['isc']['volumes']
            raw = ''.join('mount-complete volume ' + name + '\n' for name in names).encode()
            observed = dict(observed_globals=dict(_native_ufs_isc_overlay_enabled='0x1',
                _native_ufs_isc_failures='0x0', _native_ufs_isc_resident_bytes='0x1d000',
                _native_ufs_blocks_published='0x2', _native_ufs_isc_writes='0xe', _native_ufs_isc_syncs='0x4'))
            (folder / 'console.txt').write_text('Later ring tail without early mounts\n')
            (folder / 'console.json').write_text(json.dumps(dict(uuid=identity['uuid'])))
            (folder / 'stream-console.bin').write_bytes(raw)
            sample = dict(start=0, end=len(raw), missing_bytes=0, guest_dropped_bytes=0,
                          chunks=[dict(start=0, bytes=len(raw))])
            (folder / 'stream-console.jsonl').write_text(json.dumps(sample) + '\n')
            snapshot = dict(kernel_sha256=identity['kernel_sha256'], retained_log_stream=dict(
                ready=True, read_only=True, samples=1, total_bytes=len(raw), missing_bytes=0, guest_dropped_bytes=0))
            saved = folder / 'gdb-stop.json'
            saved.write_text(json.dumps(snapshot))
            with patch('package_macos26_ufs.qualify_development_dyld', return_value=observed):
                self.assertEqual(qualify_isc_overlay(folder, folder, identity, 'volume'), observed)
                (folder / 'stream-console.bin').write_bytes(raw[:-1])
                with self.assertRaisesRegex(ValueError, 'actual retained ISC stream'):
                    qualify_isc_overlay(folder, folder, identity, 'volume')
                (folder / 'stream-console.bin').write_bytes(raw)
                sample['chunks'][0]['start'] = 1
                (folder / 'stream-console.jsonl').write_text(json.dumps(sample) + '\n')
                with self.assertRaisesRegex(ValueError, 'chunk extent'):
                    qualify_isc_overlay(folder, folder, identity, 'volume')
                sample['chunks'][0]['start'] = 0
                (folder / 'stream-console.jsonl').write_text(json.dumps(sample) + '\n')
                snapshot['kernel_sha256'] = 'stale'
                saved.write_text(json.dumps(snapshot))
                with self.assertRaisesRegex(ValueError, 'actual retained ISC stream'):
                    qualify_isc_overlay(folder, folder, identity, 'volume')

    def test_isc_requires_all_role_mounts_and_bounded_failure_free_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            names = json.loads((ROOT / 'config/macos26-recovery-root.json').read_text())['isc']['volumes']
            console = ''.join('mount-complete volume ' + name + '\n' for name in names)
            values = dict(_native_ufs_isc_overlay_enabled='0x1', _native_ufs_isc_failures='0x0',
                          _native_ufs_isc_resident_bytes='0x4000000', _native_ufs_blocks_published='0x2',
                          _native_ufs_isc_writes='0xe', _native_ufs_isc_syncs='0x4')
            observed = dict(observed_globals=values)
            with patch('package_macos26_ufs.qualify_development_dyld', return_value=observed):
                (folder / 'console.txt').write_text(console)
                self.assertEqual(qualify_isc_overlay(folder, folder, {}, 'volume'), observed)
                for key, value in (('_native_ufs_isc_overlay_enabled', '0x0'),
                                   ('_native_ufs_isc_failures', '0x1'),
                                   ('_native_ufs_isc_writes', '0x0'),
                                   ('_native_ufs_isc_syncs', '0x0'),
                                   ('_native_ufs_isc_resident_bytes', '0x4000001'),
                                   ('_native_ufs_blocks_published', '0x1')):
                    original = values[key]
                    values[key] = value
                    with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'exact-candidate ISC'):
                        qualify_isc_overlay(folder, folder, {}, 'volume')
                    values[key] = original
                for name in names:
                    (folder / 'console.txt').write_text(console.replace('mount-complete volume ' + name, 'failed volume ' + name))
                    with self.subTest(missing=name), self.assertRaisesRegex(ValueError, 'exact-candidate ISC'):
                        qualify_isc_overlay(folder, folder, {}, 'volume')

    def test_stale_identity_missing_commpage_and_unreached_main_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            patch_path = ROOT / 'platform/sheng/macos26/patches/0053-development-dyld-commpage.patch'
            (folder / 'build.json').write_text(json.dumps(dict(patches={
                str(patch_path.relative_to(ROOT)): hashlib.sha256(patch_path.read_bytes()).hexdigest()})))
            identity = dict(uuid='matching', kernel_sha256='matching')
            observed = dict(identity, development_no_ignition=True, qemu_no_ignition=False,
                actual_commpage_dyld_flags='0x8', root_volume_uuid='volume',
                userland_started=True, launchd_main_started=True,
                observed_globals=dict(_sheng_development_no_ignition_enabled='0x1',
                                      _sheng_qemu_no_ignition_enabled='0x0'))
            result = folder / 'result.json'
            result.write_text(json.dumps(observed))
            self.assertEqual(qualify_development_dyld(folder, folder, identity, 'volume'), observed)
            for field, value in (('uuid', 'stale'), ('actual_commpage_dyld_flags', '0x0'),
                                 ('launchd_main_started', False), ('qemu_no_ignition', True),
                                 ('root_volume_uuid', 'wrong-volume')):
                result.write_text(json.dumps(dict(observed, **{field: value})))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'original launchd main'):
                    qualify_development_dyld(folder, folder, identity, 'volume')


if __name__ == '__main__':
    unittest.main()
