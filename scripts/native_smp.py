# SPDX-License-Identifier: GPL-3.0-or-later
"""Admit explicit CPU-only SMP observations with the paired native PAC bootstrap."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {
    'running_secondaries': ('_armcpu_smp_running', 4),
    'steps': ('_armcpu_smp_step', 32),
    'failures': ('_armcpu_smp_fail', 32),
    'psci': ('_armcpu_smp_psci_rc', 32),
    'requested_affinities': ('_armcpu_smp_mpidr', 32),
    'seen_affinities': ('_armcpu_smp_seen_mpidr', 32),
    'timer_interrupts': ('_armcpu_core_timer', 32),
    'ipi_interrupts': ('_armcpu_core_sgi', 32),
}


def configure(build: dict, count: int, graphics: bool, boot_args: str) -> dict:
    if count not in (1, 2, 4, 8) or boot_args.split().count('cpus=1') != 1:
        raise ValueError('Requires an explicit supported CPU count and the single-CPU baseline')
    if count == 1:
        return dict(cpu_count=1, boot_args=boot_args, graphics=graphics)
    if graphics:
        raise ValueError('SMP graphics requires a separate framebuffer ownership qualification')
    bootstrap = build.get('smp_bootstrap', {})
    expected = {name: hashlib.sha256((ROOT / 'platform/sheng/macos26/pac' / name).read_bytes()).hexdigest()
                for name in ('smp_keys.h', 'smp_keys_storage.h')}
    patch = ROOT / 'platform/sheng/macos26/patches/machine-cpu-smp-bootstrap.patch'
    pac_patch = ROOT / 'platform/sheng/macos26/pac/0006-native-smp-key-bootstrap.patch'
    asm_patch = ROOT / 'platform/sheng/macos26/patches/machine-cpu-inline-asm.patch'
    if (build.get('architecture') != 'arm64e' or bootstrap.get('source_sha256') != expected
            or bootstrap.get('reset_affinity_bits') != 16
            or build.get('cpu_smp_patch_sha256') != hashlib.sha256(patch.read_bytes()).hexdigest()
            or build.get('cpu_inline_asm_patch_sha256') != hashlib.sha256(asm_patch.read_bytes()).hexdigest()
            or not build.get('cpu_sgi_instructions')
            or build.get('patches', {}).get(str(pac_patch.relative_to(ROOT)))
            != hashlib.sha256(pac_patch.read_bytes()).hexdigest()):
        raise ValueError('Requires the compiled native secondary PAC and reset-affinity fixes')
    arguments = boot_args.split()
    arguments[arguments.index('cpus=1')] = f'cpus={count}'
    arguments += ['sheng-smp=1', 'armcpu-self-ipi=1']
    return dict(cpu_count=count, boot_args=' '.join(arguments), graphics=False,
                ipi='GIC SGI - QEMU', hardware_qualified=False)


def capture(memory: dict, addresses: dict, count: int) -> dict:
    import struct
    result = {}
    for field, (symbol, size) in FIELDS.items():
        raw = bytes.fromhex(memory[f'{addresses[symbol]:x}:{size:x}'])
        if len(raw) != size:
            raise ValueError('Incomplete native SMP counters')
        values = list(struct.unpack('<' + ('i' if field == 'psci' else 'I') * (size // 4), raw))
        result[field] = values[:count] if size > 4 else values[0]
    result['secondary_init_complete'] = (result['running_secondaries'] == count - 1
        and all(result['steps'][i] == 7 and result['failures'][i] == 0
                and result['psci'][i] == 0
                and result['requested_affinities'][i] & 0xffff == result['seen_affinities'][i] & 0xffff
                for i in range(1, count)))
    result['all_cores_received_timer_and_ipi'] = all(
        result['timer_interrupts'][i] > 0 and result['ipi_interrupts'][i] > 0 for i in range(count))
    result['scheduler_migration_qualified'] = False
    return result
