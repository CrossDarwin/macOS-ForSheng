#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assess UEFI preflight evidence; this module never starts a guest or writes storage."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Snapintosh/probes'))
from bootcontract import HostRuntime, PhysicalRange, Framebuffer, checked_ranges


def parse_preflight(text):
    report = {'scope': 'uefi', 'cpus': [], 'memory': [], 'enabled': None}
    for line in text.splitlines():
        if 'SHENG-PREFLIGHT: schema=' in line:
            fields = dict(re.findall(r'(\w+)=(\w+)', line))
            if fields.get('schema') != '1' or fields.get('scope') != 'uefi':
                raise ValueError('unknown preflight schema')
            report['enabled'] = int(fields['enabled'])
        if 'SHENG-PREFLIGHT: cpu=' in line:
            fields = dict(re.findall(r'(\w+)=(0x[0-9a-fA-F]+|[0-9]+)', line))
            report['cpus'].append({k: int(v, 0) for k, v in fields.items()})
        if 'SHENG-PREFLIGHT: memory ' in line:
            fields = dict(re.findall(r'(\w+)=(0x[0-9a-fA-F]+|[0-9]+)', line))
            report['memory'].append({k: int(v, 0) for k, v in fields.items()})
    if report['enabled'] is None or not report['cpus']:
        raise ValueError('incomplete preflight CPU report')
    return report


def assess(report):
    reasons = []
    if report.get('scope') != 'uefi':
        return {'ready': False, 'reasons': ['requires UEFI evidence; Linux EL0 ID values are filtered']}
    cpus = report.get('cpus', [])
    if not cpus or len(cpus) != report.get('enabled'):
        reasons.append('not all enabled CPUs were sampled')
    if len({c.get('cpu') for c in cpus}) != len(cpus):
        reasons.append('duplicate CPU samples')
    for cpu in cpus:
        name = f'cpu {cpu.get("cpu")}'
        if cpu.get('EL') != 2:
            reasons.append(f'{name}: EL2 unavailable at handoff')
        if ((cpu.get('MMFR2', 0) >> 24) & 15) < 2:
            reasons.append(f'{name}: NV2 not advertised')
        if not 0 < cpu.get('TIMER', 0) < 1 << 32:
            reasons.append(f'{name}: invalid timer frequency')
    # Register advertisement does not establish actual traps or walk behavior.
    for check in ('nv2_execution', 'debug_trap', 'granule_walk', 'pauth_execution'):
        if report.get('behavioral_checks', {}).get(check) is not True:
            reasons.append(f'{check}: not qualified')
    return {'ready': not reasons, 'reasons': reasons}


def host_runtime(info):
    """Describe a loader-owned arena, never all firmware conventional memory."""
    if info.get('current_el') != 2 or info.get('arena_owned') is not True:
        raise ValueError('requires EL2 and an exclusively allocated arena')
    timer = info.get('timer_hz', 0)
    if type(timer) is not int or not 0 < timer < 1 << 32:
        raise ValueError('invalid timer frequency')
    heap = PhysicalRange(info['arena_base'], info['arena_size'], 'sheng arena').validate()
    if heap.size < 0x501000:
        raise ValueError('arena cannot fit the q1n1-compatible monitor locator')
    fb = None
    ranges = [heap]
    if 'framebuffer' in info:
        video = info['framebuffer']
        if video['format'] not in (0, 1):
            raise ValueError('unsupported GOP pixel format')
        fb = Framebuffer(video['base'], video['width'], video['height'], video['stride_bytes'], 32)
        if fb.stride * fb.height > video['size']:
            raise ValueError('framebuffer exceeds backing allocation')
        ranges.append(fb.physical_range())
    checked_ranges(ranges)
    return HostRuntime('sheng-uefi', timer, heap, fb)


@dataclass(frozen=True)
class StorageWindow:
    """A partition-relative capability; allocation and filesystem setup are separate."""
    first_lba: int
    sectors: int
    sector_bytes: int
    device_sectors: int
    writable: bool = False

    def translate(self, lba, count, *, write=False):
        if (self.sector_bytes not in (512, 4096) or self.first_lba < 0 or self.sectors <= 0
                or self.first_lba + self.sectors > self.device_sectors):
            raise ValueError('invalid storage window')
        if lba < 0 or count <= 0 or lba + count > self.sectors:
            raise ValueError('I/O outside storage window')
        if write and not self.writable:
            raise ValueError('storage window is read-only')
        return (self.first_lba + lba) * self.sector_bytes, count * self.sector_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = parse_preflight(args.log.read_text())
    result = {'preflight': report, 'assessment': assess(report)}
    data = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data)
    print(data, end='')
    return 0 if result['assessment']['ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
