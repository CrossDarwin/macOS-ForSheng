# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from native_smp import FIELDS, capture, configure


class NativeSmpPolicy(unittest.TestCase):
    def build(self):
        pac = ROOT / 'platform/sheng/macos26/pac'
        patch = ROOT / 'platform/sheng/macos26/patches/machine-cpu-smp-bootstrap.patch'
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        return dict(architecture='arm64e', smp_bootstrap=dict(reset_affinity_bits=16,
            source_sha256={name: sha(pac / name) for name in ('smp_keys.h', 'smp_keys_storage.h')}),
            cpu_smp_patch_sha256=sha(patch),
            patches={str((pac / '0006-native-smp-key-bootstrap.patch').relative_to(ROOT)):
                     sha(pac / '0006-native-smp-key-bootstrap.patch')})

    def test_old_kernel_and_graphics_cannot_enter_cpu_only_smp(self):
        baseline = '-v cpus=1 keepsyms=1'
        self.assertEqual(configure({}, 1, True, baseline)['boot_args'], baseline)
        for count in (2, 4, 8):
            result = configure(self.build(), count, False, baseline)
            self.assertIn(f'cpus={count}', result['boot_args'].split())
            self.assertIn('sheng-smp=1', result['boot_args'].split())
            self.assertIn('armcpu-self-ipi=1', result['boot_args'].split())
            with self.assertRaises(ValueError):
                configure({}, count, False, baseline)
            with self.assertRaises(ValueError):
                configure(self.build(), count, True, baseline)

    def test_cpu_on_success_does_not_prove_cpu_init_or_irq_delivery(self):
        addresses = {symbol: 0x10000 + 0x100 * i for i, (symbol, _) in enumerate(FIELDS.values())}
        data = {field: [0] * (size // 4) for field, (_, size) in FIELDS.items()}
        def read():
            return capture({f'{addresses[symbol]:x}:{size:x}':
                struct.pack('<' + ('i' if field == 'psci' else 'I') * (size // 4), *data[field]).hex()
                for field, (symbol, size) in FIELDS.items()}, addresses, 2)
        self.assertFalse(read()['secondary_init_complete'])
        data['steps'][1] = 7
        data['running_secondaries'][0] = 1
        data['requested_affinities'][1] = 0x100
        self.assertFalse(read()['secondary_init_complete'])
        data['seen_affinities'][1] = 0x100
        result = read()
        self.assertTrue(result['secondary_init_complete'])
        self.assertFalse(result['all_cores_received_timer_and_ipi'])
        for field in ('timer_interrupts', 'ipi_interrupts'):
            data[field][:2] = [1, 1]
        self.assertTrue(read()['all_cores_received_timer_and_ipi'])
        self.assertFalse(read()['scheduler_migration_qualified'])
        data['psci'][1] = -3
        self.assertFalse(read()['secondary_init_complete'])


if __name__ == '__main__':
    unittest.main()
