#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Apply integration patches once, refusing incompatible local changes."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
for directory in sorted((ROOT / 'patches').iterdir()):
    if not directory.is_dir():
        continue
    checkout = ROOT / directory.name
    for patch in sorted(directory.glob('*.patch')):
        reverse = subprocess.run(['git', '-C', str(checkout), 'apply', '--reverse', '--check', str(patch)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if reverse.returncode == 0:
            print(f'Already applied: {patch.name}')
            continue
        subprocess.run(['git', '-C', str(checkout), 'apply', '--check', str(patch)], check=True)
        subprocess.run(['git', '-C', str(checkout), 'apply', str(patch)], check=True)
        print(f'Applied: {patch.name}')
