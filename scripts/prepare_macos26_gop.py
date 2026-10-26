#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare the pinned, default-off macOS 26.5 GOP display companion."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(root: Path, destination: Path) -> dict:
    manifest = json.loads((root / 'config/macos26-gop-reference.json').read_text())
    repository, revision = manifest['repository'], manifest['revision']
    if repository != 'Droid-VM/macOS-DroidVM' or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('requires a pinned display reference revision')
    inputs = destination / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name in ('DroidVMDisplay.cpp', 'IOMobileFramebufferABI.h'):
        entry = manifest['files'][name]
        if entry['path'] != 'overlay/kext/DroidVMDisplay/' + name:
            raise ValueError('unexpected display reference path')
        cached = inputs / name
        if cached.exists():
            data = cached.read_bytes()
        else:
            url = f'https://raw.githubusercontent.com/{repository}/{revision}/{entry["path"]}'
            with urllib.request.urlopen(url, timeout=45) as response:
                data = response.read((1 << 20) + 1)
        if len(data) > 1 << 20:
            raise ValueError('display reference exceeds the input size bound')
        data = data.rstrip(b'\n') + b'\n'
        if digest(data) != entry['canonical_sha256']:
            raise ValueError(f'pinned display reference hash mismatch: {name}')
        cached.write_bytes(data)
        (destination / name).write_bytes(data)
        hashes[name] = digest(data)
    patch = root / 'platform/sheng/macos26/display/0001-native-gop-display.patch'
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch.resolve())],
                   cwd=destination, check=True, capture_output=True, text=True)
    source = destination / 'NativeGOPDisplay.cpp'
    (destination / 'DroidVMDisplay.cpp').replace(source)
    scanout = root / 'platform/sheng/macos26/display/gop_scanout.h'
    shutil.copyfile(scanout, destination / scanout.name)
    evidence = dict(reference=f'https://github.com/{repository}/tree/{revision}',
                    input_sha256=hashes, patch_sha256=digest(patch.read_bytes()),
                    source_sha256=digest(source.read_bytes()),
                    header_sha256=digest((destination / 'IOMobileFramebufferABI.h').read_bytes()),
                    scanout_sha256=digest(scanout.read_bytes()),
                    abi=manifest['abi'],
                    build='25F71', default_off=True, boot_argument='native-gop-display=1',
                    required_cpus=1, gpu_acceleration=False, publishes_vm_identity=False,
                    runtime_qualified=False, source=str(source))
    (destination / 'source.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(Path(__file__).resolve().parents[1], args.output.resolve()), indent=2))
