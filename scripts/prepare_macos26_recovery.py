#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Decrypt the pinned recovery volume and verify its ARM64e userspace pairing."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ipsw-tool', type=Path, required=True)
    parser.add_argument('--directory', type=Path, default=ROOT / 'private/apple/macos26')
    args = parser.parse_args()
    tool = args.ipsw_tool.resolve()
    tool_pin = json.loads((ROOT / 'config/ipsw-tool.json').read_text())
    if sha(tool) != tool_pin['executable_sha256']:
        raise ValueError('ipsw executable differs from the audited release')
    profile = json.loads((ROOT / 'config/macos26.json').read_text())
    inventory = json.loads((args.directory / 'inventory.json').read_text())
    if inventory['ipsw_sha256'] != profile['ipsw']['sha256'] or inventory['build'] != profile['build']:
        raise ValueError('input inventory is not paired with the pinned IPSW')
    name = inventory['boards'][profile['device_class']]['components']['BaseSystem']
    if Path(name).name != name or not name.endswith('.dmg.aea'):
        raise ValueError('unexpected recovery archive name')
    source = args.directory / name
    if sha(source) != inventory['artifacts'][name]['sha256']:
        raise ValueError('recovery AEA input hash mismatch')
    subprocess.run([str(tool), 'fw', 'aea', str(source), '--output', str(args.directory)],
                   check=True, timeout=180)
    dmg = source.with_suffix('')
    output = args.directory / 'recovery-check'
    output.mkdir(parents=True, exist_ok=True)
    record = {'ipsw_build': profile['build'], 'ipsw_sha256': profile['ipsw']['sha256'],
              'source_aea_sha256': sha(source), 'source_dmg': dmg.name, 'dmg_sha256': sha(dmg),
              'tool_version': tool_pin['version'], 'tool_sha256': sha(tool), 'artifacts': {},
              'hardware_boot_demonstrated': False}
    for name in ('System/Library/CoreServices/SystemVersion.plist', 'sbin/launchd', 'usr/lib/dyld'):
        data = subprocess.check_output(['7z', 'e', '-so', str(dmg), name], timeout=90)
        if not 0 < len(data) <= 4 << 20:
            raise ValueError(f'{name}: invalid userspace sample size')
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.partial')
        temporary.write_bytes(data)
        temporary.replace(path)
        item = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if name.endswith('.plist'):
            version = plistlib.loads(data)
            if version['ProductBuildVersion'] != profile['build'] or version['ProductVersion'] != profile['version']:
                raise ValueError('recovery version is not paired with the kernel target')
            record['system_version'] = version
        else:
            if len(data) < 32:
                raise ValueError(f'{name}: truncated Mach-O header')
            magic, cpu, subtype, kind = struct.unpack_from('<4I', data)
            if (magic, cpu, subtype) != (0xfeedfacf, 0x100000c, 0x80000002):
                raise ValueError(f'{name}: expected ARM64e executable')
            if kind != (2 if name == 'sbin/launchd' else 7):
                raise ValueError(f'{name}: unexpected Mach-O file type')
            item.update(cpu='arm64e', cpu_subtype=hex(subtype), filetype=kind)
        record['artifacts'][name] = item
    (output / 'verification.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'PASS macOS {profile["version"]}/{profile["build"]} recovery and ARM64e launchd/dyld; hardware untested')


if __name__ == '__main__':
    main()
