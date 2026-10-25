#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Wrap paired read-only OS and optional ISC seeds inside dedicated macosroot."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

MIB = 1 << 20


def prepare(source: Path, evidence: Path, output: Path, *,
            isc_source: Path | None = None, isc_evidence: Path | None = None) -> dict:
    source = source.resolve(strict=True)
    record = json.loads(evidence.read_text())
    if (not source.is_file() or record.get('build') != '25F71'
            or record.get('read_only_qemu_input') is not True
            or type(record.get('bytes')) is not int or record['bytes'] <= 0
            or record['bytes'] % 512 or source.stat().st_size != record['bytes']
            or len(record.get('sha256', '')) != 64):
        raise ValueError('requires the paired read-only 25F71 BaseSystem raw disk evidence')
    inputs = [('OS', source, record)]
    if bool(isc_source) != bool(isc_evidence):
        raise ValueError('ISC requires both its seed and formatter evidence')
    if isc_source:
        from prepare_qemu_isc import ROLES, ISC_TYPE
        owned = json.loads(isc_evidence.read_text())
        contract = json.loads((Path(__file__).resolve().parents[1] /
                               'config/macos26-recovery-root.json').read_text())['isc']
        isc_source = isc_source.resolve(strict=True)
        if (owned.get('schema') != 'sheng-qemu-isc-v1' or owned.get('roles') != ROLES
                or owned.get('partition_type') != str(ISC_TYPE)
                or owned.get('host_devices_modified') is not False
                or owned.get('root_disk_modified') is not False
                or owned.get('sep_trusted_storage') is not False
                or owned.get('bytes') != contract['bytes']
                or owned.get('sha256') != contract['sha256']
                or owned.get('volumes') != contract['volumes']
                or not isc_source.is_file() or isc_source.stat().st_size != owned['bytes']):
            raise ValueError('ISC seed differs from the owned formatter and compiled contract')
        inputs.append(('ISC', isc_source, owned))
    windows = []
    total = MIB
    for name, path, info in inputs:
        windows.append(dict(name=name, offset=total, bytes=info['bytes'],
                            sha256=info['sha256'], source=path.name))
        total = (total + info['bytes'] + MIB - 1) // MIB * MIB
    output.mkdir(parents=True, exist_ok=False)
    image = output / 'macosroot.img'
    try:
        header = bytearray(4096)
        header[:8] = b'SHNGROOT'
        struct.pack_into('<IIQ', header, 8, 1, len(windows), total)
        with image.open('xb') as target:
            target.truncate(total)
            for index, ((_, path, info), window) in enumerate(zip(inputs, windows)):
                digest = hashlib.sha256()
                target.seek(window['offset'])
                with path.open('rb') as stream:
                    remaining = info['bytes']
                    while remaining:
                        data = stream.read(min(8 * MIB, remaining))
                        if not data:
                            raise ValueError('source disk became short during copying')
                        digest.update(data)
                        target.write(data)
                        remaining -= len(data)
                    if stream.read(1) or digest.hexdigest() != info['sha256']:
                        raise ValueError(window['name'] + ' disk differs from its paired input evidence')
                struct.pack_into('<32sQQII32s40s', header, 24 + index * 128,
                                 window['name'].encode(), window['offset'], info['bytes'],
                                 512, 1, bytes.fromhex(info['sha256']), bytes(40))
            header[4064:] = hashlib.sha256(header[:4064]).digest()
            target.seek(0)
            target.write(header)
        (output / 'manifest.bin').write_bytes(header)
        report = dict(build='25F71', partition='macosroot', root_lun=0,
                      image_bytes=total, minimum_partition_bytes=total,
                      manifest_sha256=hashlib.sha256(header).hexdigest(),
                      manifest_integrity_is_not_authentication=True, windows=windows,
                      isc_volatile_overlay=bool(isc_source), isc_seed_modified=False,
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
    parser.add_argument('--isc-image', type=Path)
    parser.add_argument('--isc-evidence', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root_image, args.root_evidence, args.output,
                             isc_source=args.isc_image, isc_evidence=args.isc_evidence), indent=2))


if __name__ == '__main__':
    main()
