#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract the paired recovery root hash for the native APFS firmware contract."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def element(data: bytes, at: int) -> tuple[int, bytes, int]:
    if at + 2 > len(data):
        raise ValueError('truncated DER element')
    tag, size = data[at:at + 2]
    at += 2
    if size & 128:
        count = size & 127
        if not 0 < count <= 4 or at + count > len(data):
            raise ValueError('invalid definite DER length')
        size = int.from_bytes(data[at:at + count], 'big')
        at += count
    if at + size > len(data):
        raise ValueError('DER element exceeds input')
    return tag, data[at:at + size], at + size


def extract(disk: Path, output: Path) -> dict:
    conversion = json.loads(disk.with_suffix('.json').read_text())
    verification = json.loads((ROOT / 'private/apple/macos26/recovery-check/verification.json').read_text())
    if (conversion['build'] != '25F71' or conversion['source'] != verification['source_dmg']
            or conversion['source_dmg_sha256'] != verification['dmg_sha256']):
        raise ValueError('requires the paired recovery conversion')
    with disk.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != conversion['sha256']:
            raise ValueError('actual disk differs from its conversion record')
    with zipfile.ZipFile(ROOT / 'private/apple/UniversalMac_26.5_25F71_Restore.ipsw') as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        if manifest['ProductBuildVersion'] != '25F71':
            raise ValueError('unexpected IPSW build')
        identities = [i for i in manifest['BuildIdentities'] if i['Info']['DeviceClass'] == 'j313ap']
        if not identities:
            raise ValueError('missing matching M1 identities')
        component = identities[0]['Manifest']['BaseSystemVolume']
        member = component['Info']['Path']
        if member != 'Firmware/' + verification['source_dmg'] + '.aea.root_hash':
            raise ValueError('root hash is not paired with the selected BaseSystem')
        wrapped = archive.read(member)
    digest = hashlib.sha384(wrapped).digest()
    if any(i['Manifest']['BaseSystemVolume']['Digest'] != digest
           or i['Manifest']['BaseSystemVolume']['Info']['Path'] != member for i in identities):
        raise ValueError('root hash does not match original manifest identities')
    tag, sequence, end = element(wrapped, 0)
    if tag != 0x30 or end != len(wrapped):
        raise ValueError('requires one complete IM4P sequence')
    fields, cursor = [], 0
    while cursor < len(sequence):
        tag, value, cursor = element(sequence, cursor)
        fields.append((tag, value))
    if ([tag for tag, _ in fields] != [22, 22, 22, 4]
            or fields[0][1] != b'IM4P' or fields[1][1] != b'csys'
            or not 16 <= len(fields[3][1]) <= 16384):
        raise ValueError('unexpected BaseSystemVolume IM4P payload')
    payload = fields[3][1]
    report = dict(build='25F71', component='BaseSystemVolume', member=member,
                  im4p_sha384=digest.hex(), manifest_digest_matches=True,
                  payload_sha256=hashlib.sha256(payload).hexdigest(), payload_bytes=len(payload),
                  payload_type='csys', raw_disk_sha256=conversion['sha256'],
                  personalized_manifest_present=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_bytes() != payload:
        raise ValueError('refuse to overwrite a different root hash')
    output.write_bytes(payload)
    Path(str(output) + '.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract(args.disk, args.output), indent=2))
