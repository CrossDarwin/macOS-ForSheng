#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package the qualified loader to recover prior RAM without starting a kernel."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def validate_recovery_fat(bpb: bytes) -> int:
    if len(bpb) < 512 or bpb[510:512] != b'\x55\xaa':
        raise ValueError('recovery configuration volume has no boot sector')
    sector_bytes, = struct.unpack_from('<H', bpb, 11)
    cluster_sectors = bpb[13]
    reserved, = struct.unpack_from('<H', bpb, 14)
    fat_sectors, = struct.unpack_from('<H', bpb, 22)
    root_entries, = struct.unpack_from('<H', bpb, 17)
    sectors = struct.unpack_from('<H', bpb, 19)[0] or struct.unpack_from('<I', bpb, 32)[0]
    if (sector_bytes != 512 or not cluster_sectors or cluster_sectors & (cluster_sectors - 1)
            or not reserved or not bpb[16] or not fat_sectors or not root_entries):
        raise ValueError('recovery configuration volume is not valid FAT16')
    root_sectors = (root_entries * 32 + sector_bytes - 1) // sector_bytes
    clusters = (sectors - reserved - bpb[16] * fat_sectors - root_sectors) // cluster_sectors
    # Firmware EnhancedFatDxe rejects FAT32 volumes below the FAT16 cluster-count threshold.
    if not 4085 <= clusters < 65525 or bpb[54:62] != b'FAT16   ':
        raise ValueError('recovery configuration volume is not valid FAT16')
    return clusters


def recovery_configuration() -> str:
    # Wait for manual selection when keys work so a countdown cannot trigger the saver before observation.
    return ('version = 1\n[boot]\ntimeout = -1\nfallback_timeout = 30\n'
            'default = "recover"\n[kits]\nautoload = false\n[[entry]]\nid = "recover"\n'
            'title = "SHENG - Save previous RAM log"\ntype = "xnu"\n'
            'path = "Payloads/recover-only.macho"\nargs = ""\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source_build.read_text())
    repair = source.get('firmware_log_repair', {})
    patch = ROOT / 'patches/UniXNU/0033-retained-log-high-bank-and-filesystem.patch'
    if (source.get('temporary_ram_boot') is not True
            or source.get('partition_images_written') is not False
            or repair.get('patch_sha256') != hashlib.sha256(patch.read_bytes()).hexdigest()
            or repair.get('partition_bound_fat_connect') is not True):
        raise ValueError('requires the packaged loader with the matching retained-log repair')
    image = (args.source_build.parent / 'sheng-macos26-kernel.img').read_bytes()
    if len(image) != source['container_bytes'] or hashlib.sha256(image).hexdigest() != source['container_sha256']:
        raise ValueError('source transport differs from its package record')
    geometry = tomllib.loads((ROOT / 'uefi-sheng/Resources/Configs/sheng.toml').read_text())['boot_image']
    pagesize, version, os_version = struct.unpack_from('<III', image, 36)
    kernel_bytes, = struct.unpack_from('<I', image, 8)
    if (image[:8] != b'ANDROID!' or version != 0 or pagesize != geometry['pagesize']
            or not os_version or kernel_bytes > len(image) - pagesize):
        raise ValueError('requires the qualified v0 firmware transport')
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(dir=args.output) as temporary:
            work = Path(temporary)
            stage = work / 'EFI/UniXNU'
            payloads = stage / 'Payloads'
            payloads.mkdir(parents=True)
            # Run NativeLogSave first, then let ParseKernel reject the marker without allocating a new kernel window or resetting the request.
            (payloads / 'recover-only.macho').write_bytes(b'SHENG - retained log recovery only\n')
            (stage / 'unixnu.toml').write_text(recovery_configuration())
            fat = work / 'recovery.fat'
            subprocess.run(['mformat', '-C', '-T', str(20 * 2048), '-v', 'SHENGLOG',
                            '-N', '53484e26', '-i', str(fat), '::'], check=True)
            with fat.open('rb') as stream:
                bpb = stream.read(512)
            clusters = validate_recovery_fat(bpb)
            subprocess.run(['mcopy', '-i', str(fat), '-s', '-Q', str(work / 'EFI'), '::/'], check=True)
            firmware = work / 'Image-dtb'
            firmware.write_bytes(image[pagesize:pagesize + kernel_bytes])
            output = work / 'sheng-macos26-kernel.img'
            command = ['python3', str(ROOT / 'uefi-sheng/Resources/Scripts/mkbootimg.py'),
                       '--kernel', str(firmware), '--ramdisk', str(fat), '-o', str(output)]
            for name in ('base', 'kernel_offset', 'tags_offset', 'pagesize', 'header_version'):
                command += ['--' + name, str(geometry[name])]
            subprocess.run(command, check=True)
            data = bytearray(output.read_bytes())
            struct.pack_into('<I', data, 44, os_version)
            (args.output / output.name).write_bytes(data)
            record = dict(temporary_ram_boot=True, partition_images_written=False,
                container_bytes=len(data), container_sha256=hashlib.sha256(data).hexdigest(),
                kernel_execution=False, kernel_window_allocation=False, config_volume_type='FAT16', config_volume_clusters=clusters,
                purpose='Recover prior RAM, then reject a non-executable marker; no new kernel or re-arm',
                source_package=str(args.source_build.parent.resolve()),
                expected_return='Malformed kernel rejected after the prior RAM log save attempt',
                log_file_writes_only='Verified macoslog PARTUUID',
                firmware_sha256=source['firmware_sha256'], firmware_log_repair=repair,
                warm_reboot_capture_qualified=False)
            (args.output / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
            print(args.output / output.name)
    except BaseException:
        shutil.rmtree(args.output)
        raise


if __name__ == '__main__':
    main()
