# SPDX-License-Identifier: MIT
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_macos26_ufs import qualify
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

    def run_qualification(self):
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
            return qualify(*self.paths, *(self.folder / name for name in ('installed.json', 'plan.json', 'root.json')))

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


if __name__ == '__main__':
    unittest.main()
