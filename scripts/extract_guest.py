#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract the small J700 boot set, using UniXNU RangeFile and Snapintosh decoders."""
import argparse
import importlib.util
import json
from pathlib import Path
import plistlib
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
sys.path.insert(0, str(ROOT / 'Snapintosh/probes'))
from unixnu.ipsw import RangeFile
from guestprofile import get_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ipsw', type=Path, help='use a fully verified local IPSW; default reads the pinned CDN')
    parser.add_argument('--output', type=Path, default=ROOT / 'private/apple/extracted/j700ap')
    args = parser.parse_args()
    guest = json.loads((ROOT / 'config/guest.json').read_text())
    spec = importlib.util.spec_from_file_location('snap_extract', ROOT / 'Snapintosh/tools/extract-firmware.py')
    decoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(decoder)
    profile = get_profile(guest['profile'])
    args.output.mkdir(parents=True, exist_ok=True)
    if not profile.validate(profile.hashes(args.output)):
        print('PASS existing J700 boot set')
        return
    source = args.ipsw if args.ipsw else RangeFile(guest['ipsw']['url'], block=1 << 20)
    with zipfile.ZipFile(source) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        if manifest.get('ProductBuildVersion') != guest['build']:
            raise ValueError('wrong IPSW build')
        identity = next(x for x in manifest['BuildIdentities']
                        if x.get('Info', {}).get('DeviceClass') == guest['device_class']
                        and x.get('Info', {}).get('RestoreBehavior') == 'Erase')
        selected = [identity['Manifest'][key]['Info']['Path']
                    for key in ('KernelCache', 'DeviceTree', 'Ap,TrustedExecutionMonitor')]
        sptm = [name for name in archive.namelist() if name.endswith('/sptm.t8140.release.im4p')]
        if len(sptm) != 1:
            raise ValueError('ambiguous SPTM input')
        selected += sptm
        for name in selected:
            raw = decoder.im4p_payload(archive.read(name))
            if raw[:4] in (b'bvx2', b'bvx-'):
                import lzfse
                data = lzfse.decompress(raw)
            else:
                data = decoder.decompress(raw, name)
            target = args.output / Path(name).name.removesuffix('.im4p')
            target.write_bytes(data)
            print(f'Extracted {target.name}: {len(data)} bytes', flush=True)
    errors = profile.validate(profile.hashes(args.output))
    if errors:
        raise ValueError('; '.join(errors))
    print('PASS J700 kernelcache, ADT, SPTM and TXM match the audited guest profile')


if __name__ == '__main__':
    main()
