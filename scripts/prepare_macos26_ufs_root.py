#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Wrap the paired BaseSystem raw disk for the dedicated read-only UFS root."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

MIB = 1 << 20


def prepare(source: Path, evidence: Path, output: Path) -> dict:
    source = source.resolve(strict=True)
    record = json.loads(evidence.read_text())
    if (not source.is_file() or record.get('build') != '25F71'
            or record.get('read_only_qemu_input') is not True
            or type(record.get('bytes')) is not int or record['bytes'] <= 0
            or record['bytes'] % 512 or source.stat().st_size != record['bytes']
            or len(record.get('sha256', '')) != 64):
        raise ValueError('requires the paired read-only 25F71 BaseSystem raw disk evidence')
    digest_bytes = bytes.fromhex(record['sha256'])
    total = (MIB + record['bytes'] + MIB - 1) // MIB * MIB
    output.mkdir(parents=True, exist_ok=False)
    image = output / 'macosroot.img'
    try:
        digest = hashlib.sha256()
        with source.open('rb') as stream, image.open('xb') as target:
            target.truncate(total)
            target.seek(MIB)
            remaining = record['bytes']
            while remaining:
                data = stream.read(min(8 * MIB, remaining))
                if not data:
                    raise ValueError('source disk became short during copying')
                digest.update(data)
                target.write(data)
                remaining -= len(data)
            if stream.read(1) or digest.digest() != digest_bytes:
                raise ValueError('BaseSystem differs from its paired raw disk evidence')
            header = bytearray(4096)
            header[:8] = b'SHNGROOT'
            struct.pack_into('<IIQ', header, 8, 1, 1, total)
            struct.pack_into('<32sQQII32s40s', header, 24, b'OS', MIB,
                             record['bytes'], 512, 1, digest_bytes, bytes(40))
            header[4064:] = hashlib.sha256(header[:4064]).digest()
            target.seek(0)
            target.write(header)
        (output / 'manifest.bin').write_bytes(header)
        report = dict(build='25F71', partition='macosroot', root_lun=0,
                      image_bytes=total, minimum_partition_bytes=total,
                      manifest_sha256=hashlib.sha256(header).hexdigest(),
                      manifest_integrity_is_not_authentication=True,
                      windows=[dict(name='OS', offset=MIB, bytes=record['bytes'],
                                    sha256=record['sha256'], source=source.name)],
                      android_userdata_used=False, hardware_qualified=False,
                      source_inputs_modified=False, partition_writes_performed=False)
        (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
        return report
    except BaseException:
        for path in (image, output / 'manifest.bin', output / 'build.json'):
            path.unlink(missing_ok=True)
        output.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-image', required=True, type=Path)
    parser.add_argument('--root-evidence', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root_image, args.root_evidence, args.output), indent=2))


if __name__ == '__main__':
    main()
