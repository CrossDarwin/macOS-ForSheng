# SPDX-License-Identifier: MIT
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from gates import assess, host_runtime, parse_preflight, StorageWindow
from guestprofile import get_profile
from check_apple import trusted_kdk_signature, kdk_kernel_pair


class Gates(unittest.TestCase):
    def test_kdk_executable_and_dwarf_share_basename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel = root / 'KDK.pkg/Payload/System/Library/Kernels/kernel.release.t8140'
            kernel.parent.mkdir(parents=True)
            kernel.touch()
            with self.assertRaisesRegex(ValueError, 'paired DWARF'):
                kdk_kernel_pair(root)
            dwarf = kernel.with_name(kernel.name + '.dSYM') / 'Contents/Resources/DWARF' / kernel.name
            dwarf.parent.mkdir(parents=True)
            dwarf.touch()
            self.assertEqual(kdk_kernel_pair(root), (kernel, dwarf))
            duplicate = root / 'unexpected/System/Library/Kernels' / kernel.name
            duplicate.parent.mkdir(parents=True)
            duplicate.touch()
            with self.assertRaisesRegex(ValueError, 'found 2'):
                kdk_kernel_pair(root)

    def test_distinct_kdk_soc_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('kernel.release.t8103', 'kernel.release.t8140'):
                kernel = root / 'Payload/System/Library/Kernels' / name
                kernel.parent.mkdir(parents=True, exist_ok=True)
                kernel.touch()
                dwarf = kernel.with_name(name + '.dSYM') / 'Contents/Resources/DWARF' / name
                dwarf.parent.mkdir(parents=True)
                dwarf.touch()
                self.assertEqual(kdk_kernel_pair(root, name), (kernel, dwarf))
            with self.assertRaisesRegex(ValueError, 'found 0'):
                kdk_kernel_pair(root, 'kernel.release.t6000')
            for name in ('../kernel.release.t8103', 'kernel.release.*'):
                with self.assertRaisesRegex(ValueError, 'invalid'):
                    kdk_kernel_pair(root, name)

    def test_apple_software_signature_status(self):
        text = 'Status: signed Apple Software\n2. Apple Software Update Certification Authority\n3. Apple Root CA\n'
        self.assertTrue(trusted_kdk_signature(text))
        self.assertFalse(trusted_kdk_signature(text.replace('signed Apple Software', 'no signature')))
        self.assertFalse(trusted_kdk_signature(text.replace('Apple Root CA', 'Untrusted Root')))
        self.assertFalse(trusted_kdk_signature('Status: signed by a certificate trusted by macOS\nDeveloper ID Installer: Someone Else'))

    def test_wrong_guest_hash_and_unknown_abi(self):
        with self.assertRaises(ValueError):
            get_profile('sheng-unverified-abi')
        profile = get_profile('j700ap-26A428')
        self.assertTrue(profile.validate({name: '0' * 64 for name, _ in profile.firmware}))

    def cpu_report(self):
        return dict(scope='uefi', enabled=1, cpus=[dict(cpu=0, EL=2, MMFR2=2 << 24, TIMER=19200000)],
                    behavioral_checks={k: True for k in ('nv2_execution', 'debug_trap', 'granule_walk', 'pauth_execution')})

    def test_no_linux_qualification(self):
        self.assertFalse(assess(self.cpu_report() | dict(scope='linux-el0-filtered'))['ready'])

    def test_required_features_and_actual_probes(self):
        self.assertTrue(assess(self.cpu_report())['ready'])
        for change in (dict(EL=1), dict(MMFR2=0), dict(MMFR2=15 << 24), dict(TIMER=0)):
            report = self.cpu_report()
            report['cpus'][0].update(change)
            self.assertFalse(assess(report)['ready'])
        report = self.cpu_report()
        report['behavioral_checks'] = {}
        self.assertFalse(assess(report)['ready'])

    def test_missing_and_duplicate_cores(self):
        report = self.cpu_report()
        report['enabled'] = 2
        self.assertFalse(assess(report)['ready'])
        report['cpus'] *= 2
        self.assertFalse(assess(report)['ready'])

    def test_parse_real_protocol_and_reject_truncation(self):
        log = 'SHENG-PREFLIGHT: schema=1 scope=uefi total=8 enabled=1\n'
        log += 'SHENG-PREFLIGHT: cpu=0 MIDR=0x411fd461 EL=1 MMFR0=0x111 MMFR1=0x0 MMFR2=0x0 ISAR1=0x0 ISAR2=0x0 DFR0=0x6 TIMER=19200000\n'
        report = parse_preflight(log)
        self.assertEqual(report['cpus'][0]['EL'], 1)
        self.assertFalse(assess(report)['ready'])
        with self.assertRaises(ValueError):
            parse_preflight(log.splitlines()[0])
        with self.assertRaises(ValueError):
            parse_preflight(log.replace('schema=1', 'schema=99'))

    def test_parse_screen_summary_and_reject_incomplete_registers(self):
        log = ('SHENG-PREFLIGHT: schema=1 scope=uefi MP=Not Found total=1 enabled=1\n'
               'SHENG-PREFLIGHT: cpu=0 MIDR=0x411fd461 EL=1\n'
               'SHENG-PREFLIGHT: MMFR0=0x111 MMFR1=0x0 MMFR2=0x0\n'
               'SHENG-PREFLIGHT: ISAR1=0x0 ISAR2=0x0 DFR0=0x6 TIMER=19200000\n')
        report = parse_preflight(log)
        self.assertEqual(report['cpus'][0]['TIMER'], 19200000)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            parse_preflight('\n'.join(log.splitlines()[:-1]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            parse_preflight(log + log.splitlines()[-1] + '\n')

    def test_owned_memory_and_framebuffer(self):
        info = dict(current_el=2, arena_owned=True, arena_base=0x80000000,
                    arena_size=0x4000000, timer_hz=19200000)
        self.assertEqual(host_runtime(info).adapter, 'sheng-uefi')
        for change in (dict(arena_owned=False), dict(current_el=1), dict(arena_base=1 << 36),
                       dict(arena_base=1), dict(arena_size=0), dict(timer_hz=0)):
            with self.assertRaises(ValueError):
                host_runtime(info | change)
        video = dict(base=0x80000000, width=3048, height=2032,
                     stride_bytes=3048*4, size=3048*2032*4, format=1)
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            host_runtime(info | dict(framebuffer=video))
        video['base'] = 0x90000000
        self.assertEqual(host_runtime(info | dict(framebuffer=video)).framebuffer.width, 3048)
        video['size'] = 4
        with self.assertRaises(ValueError):
            host_runtime(info | dict(framebuffer=video))

    def test_partition_capability(self):
        window = StorageWindow(256, 1024, 4096, 4096)
        self.assertEqual(window.translate(1023, 1), (1279*4096, 4096))
        for lba, count in ((-1, 1), (0, 0), (1023, 2), (1024, 1)):
            with self.assertRaises(ValueError):
                window.translate(lba, count)
        with self.assertRaises(ValueError):
            window.translate(0, 1, write=True)
        with self.assertRaises(ValueError):
            replace(window, first_lba=4096).translate(0, 1)


if __name__ == '__main__':
    unittest.main()
