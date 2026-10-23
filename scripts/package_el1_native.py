#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package the native EL1 UEFI probe using the existing RAM boot transport."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import tomllib

from package_reference_xnu import ROOT, vendor_dtbs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware-build', type=Path, required=True)
    p.add_argument('--backup-dir', type=Path, required=True)
    args = p.parse_args()
    firmware = json.loads(args.firmware_build.read_text())
    embedded = firmware.get('native_el1', False)
    if (firmware['preflight_only'] and not embedded) or firmware['bootimg']['compression'] != 'none':
        raise ValueError('requires an uncompressed normal or native-EL1 firmware container')
    app = None
    if embedded:
        if firmware['entry_audit']['application_guid'] != '4e240ccd-9e9a-4bf1-832d-4237392fc59f':
            raise ValueError('firmware registrar does not select the native EL1 probe')
        build = dict(sources_sha256=firmware['native_el1_sources_sha256'],
                     application_source='firmware-volume')
    else:
        build = json.loads((ROOT / 'out/native-el1-build.json').read_text())
        app = ROOT / 'out/uefi/RELEASE_CLANGPDB/AARCH64/ShengNativeEl1.efi'
        if hashlib.sha256(app.read_bytes()).hexdigest() != build['sha256']:
            raise ValueError('probe differs from its completed build')
    base = ROOT / next(x for x in firmware['artifacts'] if x.endswith('.img'))
    data = base.read_bytes()
    payload_size = struct.unpack_from('<I', data, 8)[0]
    payload = data[4096:4096 + payload_size]
    if len(payload) != payload_size:
        raise ValueError('truncated firmware payload')
    # 重用已成功启动的固件与当前槽备份，不重新提取或修改厂商固件
    with (args.backup_dir / 'boot_a.img').open('rb') as stream:
        boot = stream.read(4096)
    if boot[:8] != b'ANDROID!' or struct.unpack_from('<I', boot, 40)[0] != 4:
        raise ValueError('expected the backed-up slot A v4 boot header')
    os_version = struct.unpack_from('<I', boot, 16)[0]
    if not os_version:
        raise ValueError('missing OS metadata')
    dtb = vendor_dtbs(args.backup_dir / 'vendor_boot_a.img')
    geometry = tomllib.loads((ROOT / 'uefi-sheng/Resources/Configs/sheng.toml').read_text())['boot_image']
    if geometry['header_version'] != 0:
        raise ValueError('this transport uses the proven v0 container')
    out = ROOT / 'out/el1-native-boot'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as temp:
        work = Path(temp)
        stage = work / 'EFI/UniXNU'
        (stage / 'Payloads').mkdir(parents=True)
        if app is not None:
            shutil.copy2(app, stage / 'Payloads/ShengNativeEl1.efi')
            (stage / 'unixnu.toml').write_text(
                'version = 1\n[boot]\ntimeout = 3\ndefault = "native-el1"\n'
                '[kits]\nautoload = false\n[[entry]]\nid = "native-el1"\n'
                'title = "SHENG EL1 - 16K and PAC"\ntype = "efi"\n'
                'path = "Payloads/ShengNativeEl1.efi"\n')
        fat = work / 'probe.fat'
        subprocess.run(['mformat', '-C', '-F', '-T', str(64 * 2048), '-v', 'SHENGEL1',
                        '-N', '53484531', '-i', fat, '::'], check=True)
        subprocess.run(['mcopy', '-i', fat, '-s', '-Q', work / 'EFI', '::/'], check=True)
        kernel = work / 'Image-dtb'
        kernel.write_bytes(gzip.compress(payload, mtime=0) + dtb)
        image = work / 'sheng-native-el1.img'
        command = ['python3', ROOT / 'uefi-sheng/Resources/Scripts/mkbootimg.py',
                   '--kernel', kernel, '--ramdisk', fat, '-o', image]
        for name in ('base', 'kernel_offset', 'tags_offset', 'pagesize', 'header_version'):
            command += ['--' + name, str(geometry[name])]
        subprocess.run(command, check=True)
        blob = bytearray(image.read_bytes())
        struct.pack_into('<I', blob, 44, os_version)
        image.write_bytes(blob)
        digest = hashlib.sha256(blob).hexdigest()
        destination = out / digest
        destination.mkdir(exist_ok=True)
        shutil.copy2(image, destination / image.name)
        record = dict(container_sha256=digest, container_bytes=len(blob),
                      probe_build=build, firmware_build=str(args.firmware_build),
                      fd_sha256=firmware['sha256'], boot_slot='a',
                      os_version=os_version, header_version=0,
                      purpose='EL1 granule/PAC execution; no XNU or system volume',
                      temporary_ram_boot=True, partition_images_written=False,
                      hardware_executed=False)
        (destination / 'build.json').write_text(json.dumps(record, indent=2)+'\n')
        print(destination / image.name)


if __name__ == '__main__':
    main()
