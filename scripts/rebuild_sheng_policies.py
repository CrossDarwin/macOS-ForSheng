#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reconstruct and authenticate the pinned upstream sheng owner policies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
VOLUMES = {
    'os': dict(file='044-76040-038.dmg', bytes=6077580800,
               raw_sha256='e5634d04a8ac35f024845f583394e0a35deb26a04cb0c00286a8674e25a9a4f2',
               uuid='04769D26-2CA0-4825-B443-E2E5F88300F2'),
    'systemos': dict(file='044-76034-038.dmg', bytes=3303014400,
                     raw_sha256='b4908cde41d23e6bc05e6af51a2c9eeb00cf0f863a6a18b1600c96a3fd70414f',
                     uuid='8846FE78-2910-4297-AF97-D59BB6F8FC16'),
}
OS_PARTS = [('0.MBR', 512), ('1.Primary GPT Header', 512),
            ('2.Primary GPT Table', 16384), ('3.apfs', 6077546496),
            ('4.Backup GPT Table', 16384), ('5.Backup GPT Header', 512)]


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def raw_os(source: Path, sevenzip: str) -> Path:
    destination = source.with_suffix('.virtual-media.raw')
    if destination.exists():
        return destination
    if shutil.disk_usage(source.parent).free < VOLUMES['os']['bytes'] + 2 * 1024**3:
        raise ValueError('insufficient space for the unchanged full OS virtual media')
    temporary = destination.with_suffix('.partial')
    # UDIF extents reconstruct the whole disk, including both GPT copies.
    with temporary.open('xb') as output:
        for name, size in OS_PARTS:
            before = output.tell()
            subprocess.run([sevenzip, 'e', '-so', '-tDmg', str(source), name],
                           stdout=output, check=True)
            if output.tell() - before != size:
                raise ValueError(f'unexpected original UDIF extent: {name}')
    if sha(temporary) != VOLUMES['os']['raw_sha256']:
        raise ValueError('reconstructed OS virtual media differs from the upstream pin')
    temporary.replace(destination)
    return destination


def actual_uuid(image: Path, sevenzip: str) -> str:
    listing = subprocess.check_output([sevenzip, 'l', '-slt', str(image),
                                       'System/Library/CoreServices/SystemVersion.plist'], text=True)
    found = re.findall(r'^vol_uuid: ([0-9a-fA-F]{32})$', listing, re.MULTILINE)
    if len(found) != 1:
        raise ValueError('require exactly one actual APFS volume identity')
    return str(uuid.UUID(found[0])).upper()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, default=ROOT / 'out/sheng-xnu/work/sheng/tree')
    parser.add_argument('--inputs', type=Path, default=ROOT / 'private/apple/sheng-reference/ipsw/21H461')
    parser.add_argument('--openssl-prefix', type=Path, default=Path('/usr'))
    parser.add_argument('--sevenzip', default='7z')
    args = parser.parse_args()
    tree, inputs = args.tree.resolve(), args.inputs.resolve()
    baseline = json.loads((ROOT / 'config/sheng-baseline.json').read_text())
    if sha(ROOT / 'UniXNU-sheng/board.toml') != baseline['board_sha256']:
        raise ValueError('upstream sheng board pin changed')
    kit = ROOT / 'UniXNU/kits/VerifiedRoot'
    host = tree / 'build/verified-root-host'
    subprocess.run([sys.executable, str(kit / 'tests/check.py'), '--output', str(host),
                    '--openssl-prefix', str(args.openssl_prefix.resolve())], check=True)
    results = {}
    for name, spec in VOLUMES.items():
        source = inputs / spec['file']
        if sha(source) != baseline['ipsw']['sha256'][spec['file']]:
            raise ValueError(f'{name}: original Apple input hash mismatch')
        image = raw_os(source, args.sevenzip) if name == 'os' else source
        if image.stat().st_size != spec['bytes'] or sha(image) != spec['raw_sha256']:
            raise ValueError(f'{name}: complete original virtual media mismatch')
        volume_uuid = actual_uuid(image, args.sevenzip)
        if volume_uuid != spec['uuid']:
            raise ValueError(f'{name}: actual APFS volume identity mismatch')
        output = tree / ('build/verified-root-' + name)
        subprocess.run([sys.executable, str(kit / 'tools/manifest.py'), '--image', str(image),
                        '--private-key', str(host / 'keys/owner.pem'),
                        '--public-key', str(host / 'keys/owner-public.pem'),
                        '--volume-uuid', volume_uuid, '--generation', '1', '--output', str(output)], check=True)
        report_path = output / 'verification.json'
        subprocess.run([sys.executable, str(kit / 'tools/verify_image.py'),
                        '--library', str(host / 'verified-root.dylib'), '--manifest', str(output / 'manifest.bin'),
                        '--trusted-key', str(output / 'trusted-key.bin'), '--image', str(image),
                        '--volume-uuid', volume_uuid, '--minimum-generation', '1',
                        '--output', str(report_path)], check=True)
        report = json.loads(report_path.read_text())
        indices = [0, 1, report['blocks_verified'] // 2, report['blocks_verified'] - 1]
        lengths = []
        with image.open('rb') as stream, (output / 'original-samples.bin').open('wb') as selected:
            for index in indices:
                stream.seek(index * 4096)
                block = stream.read(min(4096, spec['bytes'] - index * 4096))
                lengths.append(len(block))
                selected.write(block.ljust(4096, b'\0'))
        report.update(actual_sample_indices=indices, actual_sample_lengths=lengths,
                      source_sha256=baseline['ipsw']['sha256'][spec['file']],
                      media_reconstruction='UDIF complete disk extents' if name == 'os' else 'original raw APFS',
                      actual_apfs_uuid_verified=True,
                      manifest_sha256=sha(output / 'manifest.bin'),
                      sample_sha256=sha(output / 'original-samples.bin'))
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        cache = tree / '.cache/firmware/target-volumes' / spec['file']
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(cache):
            cache.symlink_to(source)
        elif cache.resolve() != source.resolve():
            raise ValueError('refuse to replace an existing upstream volume input')
        results[name] = report
        print(f'PASS {name}: all {report["blocks_verified"]} actual blocks authenticated', flush=True)
    if results['os']['trusted_key_sha256'] != results['systemos']['trusted_key_sha256']:
        raise ValueError('both volumes must use the same explicit owner anchor')
    (tree / 'build/verified-root-reconstruction.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
