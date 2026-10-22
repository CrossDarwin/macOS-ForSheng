#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Refuse Apple component builds until exact inputs and ABI evidence exist."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Snapintosh/probes'))
from guestprofile import get_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--kext', action='store_true')
    choice.add_argument('--xnu', action='store_true')
    parser.add_argument('--firmware', type=Path, default=ROOT / 'private/apple/extracted/j700ap')
    parser.add_argument('--kdk', type=Path, default=Path('/Library/Developer/KDKs/KDK_27.0_26A428.kdk'))
    args = parser.parse_args()
    guest = json.loads((ROOT / 'config/guest.json').read_text())
    profile = get_profile(guest['profile'])
    problems = profile.validate(profile.hashes(args.firmware))
    if args.kext:
        if sys.platform != 'darwin':
            problems.append('arm64e kext build requires macOS, the macOS 27 SDK and kmutil')
        else:
            sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-version'], text=True).strip()
            if sdk != '27.0':
                problems.append(f'requires macOS SDK 27.0, found {sdk}')
        if not args.kdk.is_dir():
            problems.append('matching KDK_27.0_26A428.kdk is not installed')
        include = ROOT / 'Snapintosh/gpu/adreno-kext/kext/include'
        for name in ('IOMobileGraphicsFamily26A428.h', 'IOGPUFamily26A428.h'):
            if not (include / name).is_file():
                problems.append(f'private ABI header not reconstructed/verified: {name}')
    if args.xnu:
        # The existing XNU tree is Darwin 23/iPadOS 17; it cannot replace macOS 27's kernel.
        problems.append('no macOS 27 XNU source/closed-component ABI has been qualified; refusing the iPadOS baseline build')
    for problem in problems:
        print(f'BLOCKED: {problem}', file=sys.stderr)
    if problems:
        return 2
    print('PASS exact J700 firmware inputs; hardware remains unqualified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
