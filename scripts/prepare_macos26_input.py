#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage the pinned macOS VirtIO HID reference and its default-off QEMU adapter."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.request


def prepare(root: Path, destination: Path) -> dict:
    manifest = json.loads((root / 'config/macos26-input-reference.json').read_text())
    repository, revision = manifest['repository'], manifest['revision']
    if repository != 'Droid-VM/macOS-DroidVM' or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('requires a pinned input reference revision')
    paths = {
        'DroidVMInput.cpp': 'overlay/kext/DroidVMInput/DroidVMInput.cpp',
        'NativeVirtioPci.h': 'overlay/droidvm/drivers/NativeVirtioInputPci/NativeVirtioPci.h',
        'LICENSE': 'overlay/droidvm/drivers/NativeVirtioInputPci/LICENSE',
    }
    if set(manifest['files']) != set(paths):
        raise ValueError('unexpected input reference files')
    inputs = destination / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, relative in paths.items():
        entry = manifest['files'][name]
        if entry['path'] != relative:
            raise ValueError('unexpected input reference path')
        cached = inputs / name
        if cached.exists():
            data = cached.read_bytes()
        else:
            url = f'https://raw.githubusercontent.com/{repository}/{revision}/{relative}'
            with urllib.request.urlopen(url, timeout=45) as response:
                data = response.read((1 << 20) + 1)
        if len(data) > 1 << 20:
            raise ValueError('input reference exceeds size bound')
        data = data.rstrip(b'\n') + b'\n'
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry['canonical_sha256']:
            raise ValueError(f'pinned input reference hash mismatch: {name}')
        cached.write_bytes(data)
        (destination / name).write_bytes(data)
        hashes[name] = digest
    patch = root / 'platform/sheng/macos26/input/0001-native-recovery-input.patch'
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch.resolve())],
                   cwd=destination, check=True, capture_output=True, text=True)
    source = destination / 'NativeRecoveryInput.cpp'
    (destination / 'DroidVMInput.cpp').replace(source)
    evidence = dict(reference=f'https://github.com/{repository}/tree/{revision}',
        input_sha256=hashes, patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        header_sha256=hashes['NativeVirtioPci.h'], abi=manifest['abi'],
        build='25F71', default_off=True, qemu_only=True, hardware_admitted=False,
        boot_argument='native-recovery-input=1',
        provider_compatible='sheng,qemu-virtio-input',
        application_state_modified=False, runtime_qualified=False, source=str(source))
    (destination / 'source.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(Path(__file__).resolve().parents[1], args.output.resolve()), indent=2))
