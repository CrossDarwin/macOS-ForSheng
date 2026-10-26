#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Download a pinned Apple IPSW and verify its hash and board identity."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import zipfile
from range_download import download

ROOT = Path(__file__).resolve().parents[1]


def verify(path, guest, kind='ipsw'):
    spec = guest[kind]
    if path.stat().st_size != spec['bytes']:
        raise ValueError(f'{kind} size differs from pin')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != spec['sha256']:
        raise ValueError(f'{kind} SHA-256 differs from pin')
    if kind == 'kdk':
        print(f'PASS KDK download hash {digest}; Apple package signature still requires macOS verification')
        return
    with zipfile.ZipFile(path) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
    if manifest['ProductBuildVersion'] != guest['build']:
        raise ValueError('IPSW build differs from target')
    if not any(x.get('Info', {}).get('DeviceClass') == guest['device_class']
               for x in manifest['BuildIdentities']):
        raise ValueError(f'{guest["device_class"]} identity is absent')
    print(f'PASS IPSW {guest["build"]} {digest}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--kind', choices=('ipsw', 'kdk'), default='ipsw')
    parser.add_argument('--jobs', type=int, choices=range(1, 17), default=4)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/guest.json')
    parser.add_argument('--directory', type=Path, default=ROOT / 'private/apple')
    args = parser.parse_args()
    guest = json.loads(args.config.read_text())
    spec = guest[args.kind]
    args.directory.mkdir(parents=True, exist_ok=True)
    path = args.directory / spec['filename']
    if path.exists() or args.verify_only:
        verify(path, guest, args.kind)
        return
    partial = path.with_suffix(path.suffix + '.part')
    have = partial.stat().st_size if partial.exists() else 0
    if have > spec['bytes']:
        raise ValueError('partial IPSW is larger than pinned input')
    resume_map = partial.with_suffix(partial.suffix + '.ranges.json')
    allocated = partial.stat().st_blocks * 512 if partial.exists() else 0
    if shutil.disk_usage(args.directory).free < spec['bytes'] - allocated + 4 * 1024**3:
        raise ValueError('insufficient free disk space for IPSW and reserve')
    if args.jobs > 1 or resume_map.exists():
        download(spec['url'], partial, spec['bytes'], args.jobs)
    else:
        subprocess.run(['curl', '--fail', '--location', '--retry', '4', '--connect-timeout', '30',
                        '--continue-at', '-', '--output', str(partial), spec['url']], check=True)
    verify(partial, guest, args.kind)
    partial.rename(path)
    resume_map.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
