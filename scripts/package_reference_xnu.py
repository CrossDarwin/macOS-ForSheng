#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package the EL1 source reference into a RAM-only sheng boot candidate."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / 'UniXNU-sheng'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audit_kernel(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 32 or struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 2):
        raise ValueError('reference is not an ARM64 executable Mach-O')
    count, size = struct.unpack_from('<II', data, 16)
    if count > 4096 or size > len(data) - 32:
        raise ValueError('invalid Mach-O load command extent')
    offset = 32
    entry = deployment = None
    segments = []
    for _ in range(count):
        if offset + 8 > 32 + size:
            raise ValueError('truncated Mach-O command header')
        command, length = struct.unpack_from('<II', data, offset)
        if length < 8 or offset + length > 32 + size:
            raise ValueError('invalid Mach-O load command')
        if command == 0x19:
            if length < 72:
                raise ValueError('truncated Mach-O segment')
            va, vmbytes, fileoff, filebytes = struct.unpack_from('<4Q', data, offset + 24)
            if fileoff + filebytes > len(data) or filebytes > vmbytes:
                raise ValueError('Mach-O segment outside file')
            segments.append((va, fileoff, filebytes))
        elif command == 0x32:
            if length < 24:
                raise ValueError('truncated Mach-O deployment command')
            deployment = struct.unpack_from('<II', data, offset + 8)
        elif command == 5:
            if length != 288:
                raise ValueError('unsupported ARM64 entry state')
            entry = struct.unpack_from('<Q', data, offset + 272)[0]
        offset += length
    if offset != 32 + size or deployment != (2, 0x110000) or entry is None:
        raise ValueError('reference deployment or entry differs from the iOS 17 source baseline')
    if not any(va <= entry < va + length for va, _, length in segments):
        raise ValueError('Mach-O entry is not file backed')
    return {'sha256': sha(path), 'entry_va': hex(entry), 'deployment': 'iOS 17.0 source reference',
            'macos27_abi_qualified': False, 'macos_userspace_abi_qualified': False}


def vendor_dtbs(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 2128 or data[:8] != b'VNDRBOOT':
        raise ValueError('invalid vendor boot template')
    version, page, _, _, ramdisk_size = struct.unpack_from('<5I', data, 8)
    header_size, dtb_size = struct.unpack_from('<II', data, 2096)
    if version != 4 or page != 4096 or header_size != 2128 or not 0 < dtb_size <= 8 << 20:
        raise ValueError('unexpected current-slot vendor boot geometry')
    offset = ((header_size + page - 1) // page + (ramdisk_size + page - 1) // page) * page
    if offset + dtb_size > len(data):
        raise ValueError('vendor DTB region exceeds image')
    result = data[offset:offset + dtb_size]
    cursor = 0
    while cursor < len(result):
        if len(result) - cursor < 40 or result[cursor:cursor + 4] != b'\xd0\x0d\xfe\xed':
            raise ValueError('malformed concatenated vendor DTBs')
        size = struct.unpack_from('>I', result, cursor + 4)[0]
        if size < 40 or cursor + size > len(result):
            raise ValueError('vendor FDT size exceeds DTB region')
        cursor += size
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True, help='verified Actions artifact directory')
    parser.add_argument('--upstream-sheng', action='store_true',
                        help='package the complete pinned upstream configuration for an early hardware probe')
    parser.add_argument('--firmware-build', type=Path, required=True, help='normal firmware build.json, not the preflight image')
    parser.add_argument('--boot-template', type=Path, required=True, help='verified current-slot boot image backup')
    parser.add_argument('--vendor-boot-template', type=Path, required=True,
                        help='verified current-slot vendor_boot backup; retains DTBO compatibility')
    parser.add_argument('--compression', choices=('gzip', 'none'), default='gzip')
    parser.add_argument('--mmu-reset-delay', type=int, choices=range(1, 11),
                        help='diagnostic reset this many seconds after the post-MMU probe is reached')
    parser.add_argument('--reset-after', help='move the diagnostic reset after this verified arm_init call')
    parser.add_argument('--reset-before', action='store_true', help='stop before the selected call')
    parser.add_argument('--reset-in', default='_arm_init', help='function containing the selected call')
    args = parser.parse_args()
    if args.reset_before and not args.reset_after:
        parser.error('--reset-before requires --reset-after')
    if args.reset_after and not args.mmu_reset_delay:
        parser.error('--reset-after requires --mmu-reset-delay')
    for path in (args.boot_template, args.vendor_boot_template):
        manifest = json.loads((path.parent / 'manifest.json').read_text())
        expected = manifest['images'].get(path.stem)
        if (not expected or expected['file'] != path.name or expected['bytes'] != path.stat().st_size
                or expected['sha256'] != sha(path)):
            raise ValueError(f'{path.name}: backup manifest verification failed')
    build = json.loads((args.kernel_build / 'build.json').read_text())
    original = args.kernel_build / 'kernel.macho'
    expected_config = ROOT / ('config/sheng_defconfig' if args.upstream_sheng else 'config/reference-xnu_defconfig')
    if (not build.get('built') or build.get('xnu') != '10063.141.1'
            or build.get('kernel_sha256') != sha(original)
            or build.get('defconfig_sha256') != sha(expected_config)
            or build.get('original_abi_bootstrap_only')
            or (not args.upstream_sheng and build.get('config', {}).get('XNU_NATIVE_UFS'))):
        raise ValueError('reference build provenance or kernel hash mismatch')
    if args.upstream_sheng:
        baseline = json.loads((ROOT / 'config/sheng-baseline.json').read_text())
        if (not build.get('full_upstream_sheng_config') or not build.get('prelinked')
                or build.get('upstream_board_sha256') != baseline['board_sha256']
                or build.get('upstream_defconfig_sha256') != baseline['defconfig_sha256']
                or build.get('archives') != baseline['archives']):
            raise ValueError('requires every pinned upstream sheng option and archive')
        checkpoint = (args.reset_in, args.reset_after, args.reset_before)
        if not args.mmu_reset_delay or checkpoint not in {
                ('_arm_init', '_PE_create_console', False),
                ('_kernel_bootstrap_thread', '_bsd_init', True),
                ('_bsd_init', '_IOKitInitializeTime', True),
                ('_bsd_init', '_IOKitBSDInit', True)}:
            raise ValueError('complete-config test requires a bounded console or pre-autoconfiguration BSD checkpoint')
    audit = audit_kernel(original)
    translation = json.loads((args.kernel_build / 'kernel-audit.json').read_text())
    translation_hash = build.get('source_kernel_sha256') if args.upstream_sheng else audit['sha256']
    if (translation.get('sha256') != translation_hash
            or translation.get('tg0_bytes') != 4096 or translation.get('tg1_bytes') != 4096):
        raise ValueError('reference lacks a matching 4 KiB translation audit')
    if args.upstream_sheng:
        from observe_sheng_abi import symbols
        sysreg = symbols(original)['_sysreg_restore']
        data = original.read_bytes()
        cursor = 32
        actual_tcr = None
        for _ in range(struct.unpack_from('<I', data, 16)[0]):
            command, size = struct.unpack_from('<II', data, cursor)
            if command == 0x19:
                address, _, offset, length = struct.unpack_from('<4Q', data, cursor + 24)
                if address <= sysreg and sysreg + 8 <= address + length:
                    actual_tcr = struct.unpack_from('<Q', data, offset + sysreg - address)[0]
            cursor += size
        if actual_tcr is None or actual_tcr != int(translation['initial_tcr'], 16):
            raise ValueError('prelinked kernel initial TCR differs from its source audit')
        audit['initial_tcr'] = hex(actual_tcr)
    firmware = json.loads(args.firmware_build.read_text())
    if firmware.get('preflight_only') is not False or not firmware['entry_audit']['registrar_pcd_checked']:
        raise ValueError('requires the audited normal UniXNU firmware entry')
    base_image = ROOT / next(path for path in firmware['artifacts'] if path.endswith('.img'))
    base_data = base_image.read_bytes()
    if sha(base_image) != firmware['bootimg']['container_sha256'] or firmware['bootimg']['compression'] != 'none':
        raise ValueError('normal firmware container hash or encoding mismatch')
    kernel_size = struct.unpack_from('<I', base_data, 8)[0]
    payload = base_data[4096:4096 + kernel_size]
    if hashlib.sha256(payload).hexdigest() != firmware['bootimg']['payload_sha256']:
        raise ValueError('firmware payload hash mismatch')
    with args.boot_template.open('rb') as stream:
        template = stream.read(4096)
    if template[:8] != b'ANDROID!' or struct.unpack_from('<I', template, 40)[0] != 4:
        raise ValueError('expected a current-slot Android v4 template')
    os_version = struct.unpack_from('<I', template, 16)[0]
    if not os_version:
        raise ValueError('current-slot OS metadata is missing')
    config = tomllib.loads((ROOT / 'uefi-sheng/Resources/Configs/sheng.toml').read_text())['boot_image']
    out = ROOT / ('out/sheng-upstream-boot' if args.upstream_sheng else 'out/reference-boot')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stage-', dir=out) as temporary:
        work = Path(temporary)
        stage = work / 'stage'
        files = stage / 'EFI/UniXNU/Payloads'
        files.mkdir(parents=True)
        kernel = files / 'kernel.macho'
        shutil.copy2(original, kernel)
        env = dict(os.environ, UNIXNU_UEFI=str(ROOT / 'uefi-sheng'))
        probe = ['python3', DEVICE / 'scripts/patch-xnu-entry-probe.py', kernel]
        probe += (['--reset-delay', str(args.mmu_reset_delay)] if args.mmu_reset_delay
                  else ['--panic-screen', '--no-reset'])
        if args.reset_after:
            probe += ['--reset-after', args.reset_after, '--in', args.reset_in]
        if args.reset_before:
            probe += ['--reset-before']
        subprocess.run(probe, env=env, check=True)
        adt = files / 'kernel.macho.adt'
        owned_memory = 0x40000000 if args.upstream_sheng else 0x20000000
        subprocess.run(['python3', DEVICE / 'scripts/make-sheng-adt.py', '--output', adt,
                        '--dram-size', '0x200000000', '--owned-memory-size', hex(owned_memory),
                        '--cpu-regs', '0', '--cpu-compatible', 'arm,cortex-a510'], check=True)
        (stage / 'EFI/UniXNU/unixnu.toml').write_text(
            'version = 1\n[boot]\ntimeout = 3\ndefault = "el1-reference"\n[kits]\nautoload = false\n'
            '[[entry]]\nid = "el1-reference"\ntitle = "EL1 XNU ' +
            ('full sheng' if args.upstream_sheng else 'reference') + ' - no OS image"\n'
            'type = "xnu"\npath = "Payloads/kernel.macho"\n'
            'args = "-v debug=0x100 keepsyms=1 cpus=1"\n')
        for path in [stage, *stage.rglob('*')]:
            os.utime(path, (315532800, 315532800))
        fat = work / 'payload.img'
        content = sum(path.stat().st_size for path in stage.rglob('*') if path.is_file())
        budget = content + max(16 << 20, content // 4) if args.upstream_sheng else content * 2
        mib = max(64, ((budget + (1 << 20) - 1) >> 20))
        if mib > 192:
            raise ValueError('reference payload exceeds the bounded RAM image size')
        subprocess.run(['mformat', '-C', '-F', '-T', str(mib * 2048), '-v', 'SHENGREF',
                        '-N', '53484e47', '-i', fat, '::'], check=True)
        subprocess.run(['mcopy', '-i', fat, '-s', '-Q', '-m', stage / 'EFI', '::/'], check=True)
        # Verify the actual FAT read-back before including it in the Android container.
        roundtrip = work / 'readback.macho'
        subprocess.run(['mcopy', '-i', fat, '::/EFI/UniXNU/Payloads/kernel.macho', roundtrip], check=True)
        if sha(roundtrip) != sha(kernel):
            raise ValueError('FAT kernel read-back differs')
        dtbytes = vendor_dtbs(args.vendor_boot_template)
        blob = work / 'Image-dtb'
        # ABL obtains the v0 appended-DTB offset from gzip decompression.
        transport = gzip.compress(payload, mtime=0) if args.compression == 'gzip' else payload
        blob.write_bytes(transport + dtbytes)
        image = work / 'sheng-el1-reference.img'
        command = ['python3', ROOT / 'uefi-sheng/Resources/Scripts/mkbootimg.py',
                   '--kernel', blob, '--ramdisk', fat, '-o', image]
        for key in ('base', 'kernel_offset', 'tags_offset', 'pagesize', 'header_version'):
            command += ['--' + key, str(config[key])]
        subprocess.run(command, check=True)
        data = bytearray(image.read_bytes())
        if config['header_version'] != 0:
            raise ValueError('reference RAM transport currently requires v0')
        struct.pack_into('<I', data, 44, os_version)
        image.write_bytes(data)
        ksize, _, rsize = struct.unpack_from('<3I', data, 8)
        page = struct.unpack_from('<I', data, 36)[0]
        ramoff = page + ((ksize + page - 1) // page) * page
        if (data[:8] != b'ANDROID!' or ksize != blob.stat().st_size or rsize != fat.stat().st_size
                or data[page:page + ksize] != blob.read_bytes()
                or data[ramoff:ramoff + rsize] != fat.read_bytes()):
            raise ValueError('Android kernel/ramdisk round-trip mismatch')
        record = {'purpose': 'EL1 source-kernel hardware test; no macOS userspace',
                  'kernel_audit': audit, 'source_build_sha256': sha(args.kernel_build / 'build.json'),
                  'firmware_build_sha256': sha(args.firmware_build), 'fd_sha256': firmware['sha256'],
                  'instrumented_kernel_sha256': sha(kernel), 'adt_sha256': sha(adt),
                  'fat_sha256': sha(fat), 'fat_bytes': fat.stat().st_size,
                  'dtb_sha256': hashlib.sha256(dtbytes).hexdigest(),
                  'vendor_boot_template_sha256': sha(args.vendor_boot_template),
                  'dtb_source': 'current-slot vendor_boot; ABL selects and overlays the matching stock FDT',
                  'boot_template_sha256': sha(args.boot_template),
                  'os_version': os_version, 'header_version': 0, 'cpu_scope': 'boot Cortex-A510 only',
                  'compression': args.compression, 'uncompressed_payload_sha256': hashlib.sha256(payload).hexdigest(),
                  'post_mmu_reset_delay_seconds': args.mmu_reset_delay,
                  'reset_after_arm_init_call': args.reset_after if args.reset_in == '_arm_init' and not args.reset_before else None,
                  'reset_checkpoint': {'function': args.reset_in, 'callee': args.reset_after,
                                       'position': 'before' if args.reset_before else 'after'},
                  'entry_probe_sha256': sha(DEVICE / 'scripts/patch-xnu-entry-probe.py'),
                  'panic_screen_enabled': args.mmu_reset_delay is None,
                  'owned_memory_bytes': owned_memory, 'container_sha256': sha(image),
                  'container_bytes': image.stat().st_size, 'hardware_executed': False,
                  'full_upstream_sheng_config': args.upstream_sheng,
                  'persistent_storage_drivers_linked': args.upstream_sheng,
                  'stop_before_iokit': args.upstream_sheng and args.reset_in == '_arm_init',
                  'stop_before_bsd': args.upstream_sheng and args.reset_in != '_bsd_init',
                  'stop_before_root_mount': args.upstream_sheng,
                  'partition_images_written': False}
        destination = out / record['container_sha256']
        destination.mkdir(exist_ok=False)
        shutil.copy2(image, destination / image.name)
        shutil.copy2(adt, destination / adt.name)
        (destination / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
