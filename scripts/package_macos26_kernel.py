#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package the native SHENG kernel and retained logger for RAM-only boot."""
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

from observe_macos26_kernel import identify, ROOT
from package_reference_xnu import vendor_dtbs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--firmware-build', type=Path, required=True)
    parser.add_argument('--backup-dir', type=Path, required=True)
    args = parser.parse_args()
    kernel, symbols, audit = identify(args.kernel_build.resolve())
    if '_sheng_log_buffer' not in symbols:
        raise ValueError('native hardware candidate requires the retained kernel logger')
    firmware = json.loads(args.firmware_build.read_text())
    patch = 'patches/UniXNU/0007-native-16k-bootstrap-congruence.patch'
    if (firmware.get('preflight_only') is not False or firmware.get('native_el1')
            or firmware['bootimg']['compression'] != 'none'
            or firmware.get('patches_sha256', {}).get(patch) != hashlib.sha256((ROOT / patch).read_bytes()).hexdigest()):
        raise ValueError('requires normal firmware with the native 32 MiB loader constraint')
    base = ROOT / next(name for name in firmware['artifacts'] if name.endswith('.img'))
    base_data = base.read_bytes()
    if hashlib.sha256(base_data).hexdigest() != firmware['bootimg']['container_sha256']:
        raise ValueError('firmware image differs from its completed build')
    payload_size = struct.unpack_from('<I', base_data, 8)[0]
    payload = base_data[4096:4096 + payload_size]
    if len(payload) != payload_size:
        raise ValueError('firmware payload is truncated')
    with (args.backup_dir / 'boot_a.img').open('rb') as stream:
        boot = stream.read(4096)
    if boot[:8] != b'ANDROID!' or struct.unpack_from('<I', boot, 40)[0] != 4:
        raise ValueError('requires the backed-up Android v4 slot A header')
    os_version = struct.unpack_from('<I', boot, 16)[0]
    if not os_version:
        raise ValueError('missing current-slot OS metadata')
    dtbs = vendor_dtbs(args.backup_dir / 'vendor_boot_a.img')
    geometry = tomllib.loads((ROOT / 'uefi-sheng/Resources/Configs/sheng.toml').read_text())['boot_image']
    if geometry['header_version'] != 0:
        raise ValueError('native RAM boot transport requires the proven v0 container')
    out = ROOT / 'out/macos26-kernel-boot'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as temporary:
        work = Path(temporary)
        stage = work / 'EFI/UniXNU'
        files = stage / 'Payloads'
        files.mkdir(parents=True)
        shutil.copy2(kernel, files / 'kernel.macho')
        subprocess.run(['python3', ROOT / 'UniXNU-sheng/scripts/make-sheng-adt.py',
                        '--output', files / 'kernel.macho.adt', '--dram-size', '0x200000000',
                        '--owned-memory-size', '0x20000000', '--cpu-regs', '0',
                        '--cpu-compatible', 'arm,cortex-a510', '--random-seed-bytes', '256'], check=True)
        (stage / 'unixnu.toml').write_text(
            'version = 1\n[boot]\ntimeout = 3\ndefault = "native26"\n'
            '[kits]\nautoload = false\n[[entry]]\nid = "native26"\n'
            'title = "SHENG macOS 26 - native kernel with RAM log"\n'
            'type = "xnu"\npath = "Payloads/kernel.macho"\n'
            'args = "-v debug=0x14e keepsyms=1 cpus=1 -enable_kprintf_spam"\n')
        content = sum(path.stat().st_size for path in stage.rglob('*') if path.is_file())
        mib = max(64, (content * 2 + (1 << 20) - 1) >> 20)
        if mib > 192:
            raise ValueError('kernel exceeds the bounded RAM FAT budget')
        fat = work / 'native.fat'
        subprocess.run(['mformat', '-C', '-F', '-T', str(mib * 2048), '-v', 'SHENGXNU26',
                        '-N', '53484e26', '-i', fat, '::'], check=True)
        subprocess.run(['mcopy', '-i', fat, '-s', '-Q', work / 'EFI', '::/'], check=True)
        transport = work / 'Image-dtb'
        transport.write_bytes(gzip.compress(payload, mtime=0) + dtbs)
        image = work / 'sheng-macos26-kernel.img'
        command = ['python3', ROOT / 'uefi-sheng/Resources/Scripts/mkbootimg.py',
                   '--kernel', transport, '--ramdisk', fat, '-o', image]
        for name in ('base', 'kernel_offset', 'tags_offset', 'pagesize', 'header_version'):
            command += ['--' + name, str(geometry[name])]
        subprocess.run(command, check=True)
        data = bytearray(image.read_bytes())
        struct.pack_into('<I', data, 44, os_version)
        image.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        destination = out / digest
        destination.mkdir(exist_ok=False)
        shutil.copy2(image, destination / image.name)
        shutil.copy2(files / 'kernel.macho.adt', destination / 'kernel.macho.adt')
        record = dict(container_sha256=digest, container_bytes=len(data), kernel=audit,
                      log_symbol_va=hex(symbols['_sheng_log_buffer']),
                      log_physical_address='actual DarwinBoot PA + log_symbol_va - kernel linked base',
                      bootstrap_block_bytes=33554432, owned_memory_bytes=0x20000000,
                      firmware_sha256=firmware['sha256'], temporary_ram_boot=True,
                      hardware_executed=False, userland_started=False,
                      storage_drivers_linked=False, partition_images_written=False)
        (destination / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
        print(destination / image.name)


if __name__ == '__main__':
    main()
