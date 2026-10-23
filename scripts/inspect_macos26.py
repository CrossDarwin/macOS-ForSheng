#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify the paired macOS 26 IPSW and extract bounded bring-up inputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from fetch_inputs import verify


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'private/apple/macos26')
    args = parser.parse_args()
    profile = json.loads((ROOT / 'config/macos26.json').read_text())
    source = ROOT / 'private/apple' / profile['ipsw']['filename']
    verify(source, profile)
    args.output.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('firmware_decoder', ROOT / 'Snapintosh/tools/extract-firmware.py')
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    import lzfse
    record = {'version': profile['version'], 'build': profile['build'],
              'ipsw_sha256': profile['ipsw']['sha256'], 'boards': {}, 'artifacts': {},
              'hardware_qualified': False, 'recovery_userspace_verified': False}
    with zipfile.ZipFile(source) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        if manifest['ProductVersion'] != profile['version']:
            raise ValueError('IPSW product version differs from target')
        paths = set()
        for board in (*profile['candidate_boards'], 'vma2macosap'):
            identities = [item for item in manifest['BuildIdentities']
                          if item.get('Info', {}).get('DeviceClass') == board
                          and item['Info'].get('Variant') == 'Customer Erase Install (IPSW)']
            if len(identities) != 1:
                raise ValueError(f'ambiguous production identity: {board}')
            identity = identities[0]
            components = {key: item['Info']['Path'] for key, item in identity['Manifest'].items()
                          if key in ('KernelCache', 'DeviceTree', 'BaseSystem', 'OS',
                                     'Cryptex1,SystemOS', 'RestoreRamDisk', 'Ap,TrustedExecutionMonitor')
                          or 'SPTM' in key}
            record['boards'][board] = {'components': components}
            paths.update(value for key, value in components.items()
                         if key not in ('OS', 'Cryptex1,SystemOS'))
        common = ('BaseSystem', 'OS', 'Cryptex1,SystemOS', 'RestoreRamDisk')
        for key in common:
            if len({item['components'].get(key) for item in record['boards'].values()}) != 1:
                raise ValueError(f'board system pairing differs: {key}')
        needed = sum(archive.getinfo(name).file_size for name in paths)
        if needed > 6 * 1024**3 or shutil.disk_usage(args.output).free < needed + 4 * 1024**3:
            raise ValueError('bounded extraction exceeds available disk budget')
        for name in sorted(paths):
            member = Path(name)
            if member.is_absolute() or '..' in member.parts:
                raise ValueError('invalid IPSW member path')
            target = args.output / member
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + '.partial')
            with archive.open(name) as stream, temporary.open('wb') as output:
                shutil.copyfileobj(stream, output, 1 << 20)
            temporary.replace(target)
            item = {'bytes': target.stat().st_size, 'sha256': digest(target)}
            if name.startswith('kernelcache.') or member.suffix == '.im4p':
                payload = decoder.im4p_payload(target.read_bytes())
                if payload[:4] in (b'bvx2', b'bvx-'):
                    payload = lzfse.decompress(payload)
                else:
                    payload = decoder.decompress(payload, name)
                decoded = target.with_name(target.name + '.decoded')
                decoded.write_bytes(payload)
                item['decoded'] = {'sha256': digest(decoded), 'bytes': len(payload)}
                if name.startswith('kernelcache.'):
                    versions = sorted({value.decode('ascii') for value in re.findall(
                        rb'Darwin Kernel Version [\x20-\x7e]{1,400}', payload)})
                    if len(versions) != 1 or ('xnu-' + profile['source']['xnu_version']) not in versions[0]:
                        raise ValueError(f'{name}: binary XNU version does not match published source')
                    item['darwin_version'] = versions[0]
            record['artifacts'][name] = item
            print(f'Extracted {name}: {item["bytes"]} bytes', flush=True)
    (args.output / 'inventory.json').write_text(json.dumps(record, indent=2) + '\n')
    print('PASS paired M1, Neo and VMAPPLE inputs; recovery userspace still requires inspection')


if __name__ == '__main__':
    main()
