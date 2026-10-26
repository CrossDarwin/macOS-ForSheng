#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract only native PAC counters from the matching kernel DWARF layout."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from observe_macos26_kernel import identify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--dwarfdump', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    _, _, identity = identify(args.kernel_build)
    if identity['architecture'] != 'arm64e':
        parser.error('requires the native ARM64E kernel and matching DWARF')
    dwarf, = (args.kernel_build / 'kernel.development.sheng.dSYM/Contents/Resources/DWARF').iterdir()
    text = subprocess.check_output([args.dwarfdump, '--name=cpu_data', '--show-children', dwarf],
                                   text=True, timeout=60)
    offsets = {}
    for field in ('signing', 'entries', 'returns', 'signs'):
        pattern = (r'DW_AT_name\s+\("sheng_pac_' + field + r'"\)'
                   r'(?:(?!DW_TAG_).)*?DW_AT_data_member_location\s+\((0x[0-9a-f]+)\)')
        found = {int(value, 16) for value in re.findall(pattern, text, re.S)}
        if len(found) != 1:
            raise ValueError(f'no unique compiler layout for PAC {field}: {found}')
        offsets[field] = found.pop()
    start = offsets['signing']
    if not 0x100 <= start < 0x10000 or list(offsets.values()) != list(range(start, start + 32, 8)):
        raise ValueError('PAC diagnostic fields are not four bounded contiguous counters')
    result = dict(kernel_uuid=identity['uuid'], kernel_sha256=identity['kernel_sha256'],
                  cpu_data_offsets=offsets, bytes=32, contains_key_material=False,
                  source='matching cpu_data DWARF members')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
