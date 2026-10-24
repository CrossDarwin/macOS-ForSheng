#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Observe the linked native macOS 26 kernel through UniXNU's QEMU entry path."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid

from native_macho import macho, symbols
from native_devtree import configure_native_text_state

ROOT = Path(__file__).resolve().parents[1]
NATIVE_BOOT_ARGS = '-v debug=0x14e keepsyms=1 cpus=1 -enable_kprintf_spam'
sys.path.insert(0, str(ROOT / 'UniXNU/kits/NativePrelink'))
from native_prelink import backed_offset


def identify(build_dir: Path) -> tuple[Path, dict, dict]:
    build = json.loads((build_dir / 'build.json').read_text())
    kernel = build_dir / 'kernel.development.sheng'
    data = kernel.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if (build.get('xnu') != '12377.121.6' or build.get('build') != '25F71'
            or build.get('machine') != 'SHENG' or not build.get('executable_kernel_built')
            or digest != build.get('executable_kernel_sha256')):
        raise ValueError('requires the actual linked SHENG macOS 26.5 artifact')
    architecture = build.get('architecture', 'arm64')
    image = macho(data, architecture)
    if image['kind'] != 2:
        raise ValueError('requires an executable kernel, not its source archive')
    entry = deployment = identity = None
    for kind, offset, size in image['commands']:
        if kind == 5:
            if size != 288 or struct.unpack_from('<II', data, offset + 8) != (6, 68):
                raise ValueError('unsupported ARM64 UNIXTHREAD state')
            entry = struct.unpack_from('<Q', data, offset + 272)[0]
        elif kind == 0x32:
            deployment = struct.unpack_from('<II', data, offset + 8)
        elif kind == 0x1b:
            identity = str(uuid.UUID(bytes=data[offset + 8:offset + 24])).upper()
    if deployment != (1, 0x1a0500) or entry is None or identity is None:
        raise ValueError('kernel lacks its macOS 26.5 deployment, entry or UUID')
    for segment in image['segments']:
        if segment['fileoff'] + segment['filesize'] > len(data):
            raise ValueError('kernel segment exceeds its backing file')
    backed_offset(image['segments'], entry, 4, len(data))
    if not any(s['initprot'] & 4 and s['va'] <= entry < s['va'] + s['filesize']
               for s in image['segments']):
        raise ValueError('entry is not in an executable file-backed segment')
    addresses = symbols(kernel)
    if entry != addresses.get('__start') or min(s['va'] for s in image['segments']
            if s['size']) != 0xfffffe0007004000:
        raise ValueError('entry or linked base differs from the native SHENG layout')
    dwarfs = list((build_dir / 'kernel.development.sheng.dSYM/Contents/Resources/DWARF').iterdir())
    if len(dwarfs) != 1 or not dwarfs[0].is_file():
        raise ValueError('requires exactly one linked kernel DWARF image')
    dwarf_data = dwarfs[0].read_bytes()
    dwarf_image = macho(dwarf_data, architecture)
    dwarf_ids = [str(uuid.UUID(bytes=dwarf_data[at + 8:at + 24])).upper()
                 for kind, at, _ in dwarf_image['commands'] if kind == 0x1b]
    if dwarf_ids != [identity]:
        raise ValueError('debug symbols do not belong to this linked kernel')
    return kernel, addresses, dict(kernel_sha256=digest, uuid=identity,
        entry_va=hex(entry), segments=image['segments'], deployment='macOS 26.5',
        architecture=architecture, hardware_executed=False, userland_started=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--loader-build', type=Path, default=ROOT / 'out/native-loader/build.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed-bytes', type=int, choices=(64, 256), default=256,
                        help='64 is the explicit insufficient-entropy panic experiment')
    parser.add_argument('--capture-panic-buffer', action='store_true',
                        help='save the owned 512 KiB XNU panic region through its actual gPanicBase pointer')
    parser.add_argument('--let-vector-log', action='store_true',
                        help='allow the kernel exception hook to retain the first fault before a bounded stop')
    parser.add_argument('--capture-screen', action='store_true', help='save the actual QEMU framebuffer')
    parser.add_argument('--handoff-pause', action='store_true', help='exercise the ten-second hardware handoff capture window')
    parser.add_argument('--early-console', action='store_true', help='acquire the inherited GOP through the XNU text console')
    parser.add_argument('--checkpoint', choices=('arm_init', 'arm_vm_init',
                        'PE_create_console', 'bsd_init', 'IOFindBSDRoot',
                        'native_virtio_read_checkpoint', 'bsdinit_task', 'load_init_program',
                        'thread_setentrypoint'), default='arm_init')
    parser.add_argument('--follow-init-entry', action='store_true',
                        help='follow thread_setentrypoint x1 into actual EL0 and step 16 instructions')
    parser.add_argument('--follow-launchd-main', action='store_true',
                        help='follow the paired launchd LC_MAIN from the actual dyld startup stack')
    parser.add_argument('--trace-init-syscalls', action='store_true',
                        help='retain bounded real Unix/Mach saved-state calls after init starts')
    parser.add_argument('--virtio-block-image', type=Path, help='existing raw disk attached strictly read-only')
    parser.add_argument('--root-volume-uuid', type=uuid.UUID, help='match the actual APFS volume UUID')
    parser.add_argument('--qemu-no-ignition', action='store_true',
                        help='explicit development-only use of original dyld skipIgnition bit')
    parser.add_argument('--root-hash-payload', type=Path,
                        help='paired raw BaseSystemVolume payload and conversion evidence')
    parser.add_argument('--qemu-development-root', action='store_true',
                        help='explicit QEMU CSR policy allowing the unauthenticated experiment root')
    parser.add_argument('--kext-log', type=lambda value: int(value, 0),
                        help='enable the existing XNU kextlog filter for this QEMU run')
    parser.add_argument('--timeout', type=int, default=60, metavar='SECONDS')
    parser.add_argument('--decode-existing-snapshot', action='store_true',
                        help='decode a saved snapshot without restarting QEMU')
    args = parser.parse_args()
    if not 15 <= args.timeout <= 180:
        parser.error('--timeout must be between 15 and 180 seconds')
    if args.kext_log is not None and not 0 <= args.kext_log <= 0xffffffff:
        parser.error('--kext-log must be a 32-bit unsigned filter')
    kernel, addresses, record = identify(args.kernel_build.resolve())
    security_path = args.kernel_build / 'security-relink.json'
    if security_path.is_file():
        component_map = json.loads(security_path.read_text())
        if component_map['candidate_sha256'] != record['kernel_sha256']:
            raise ValueError('component symbol map differs from the actual candidate')
        for name, value in component_map.get('storage_driver', {}).get('symbols', {}).items():
            if not name.startswith('_native_virtio_'):
                continue
            if name in addresses and addresses[name] != value:
                raise ValueError('transport symbol collides with the native kernel')
            addresses[name] = value
    if args.follow_init_entry and args.checkpoint != 'thread_setentrypoint':
        parser.error('following init requires the thread_setentrypoint checkpoint')
    if args.root_volume_uuid and not args.virtio_block_image:
        parser.error('APFS volume matching requires the actual block image')
    if args.qemu_no_ignition and (not args.qemu_development_root or not args.root_hash_payload):
        parser.error('no ignition requires the paired root hash and explicit QEMU development root')
    launchd_main = None
    if args.follow_launchd_main:
        if not args.follow_init_entry:
            parser.error('launchd main observation requires --follow-init-entry')
        directory = ROOT / 'private/apple/macos26/recovery-check'
        launchd = (directory / 'sbin/launchd').read_bytes()
        recovery = json.loads((directory / 'verification.json').read_text())
        expected = recovery['artifacts']['sbin/launchd']['sha256']
        if hashlib.sha256(launchd).hexdigest() != expected:
            raise ValueError('launchd differs from the paired recovery input')
        executable = macho(launchd, 'arm64e')
        main = [at for kind, at, size in executable['commands'] if kind == 0x80000028 and size == 24]
        if len(main) != 1:
            raise ValueError('requires one original launchd LC_MAIN')
        launchd_main = struct.unpack_from('<Q', launchd, main[0] + 8)[0]
        record['launchd_main_input'] = dict(sha256=expected, entry_offset=launchd_main)
    root_hash = None
    if args.root_hash_payload:
        if not args.virtio_block_image or not args.root_volume_uuid:
            parser.error('root hash requires the actual disk and volume identity')
        root_hash = args.root_hash_payload.read_bytes()
        evidence = json.loads(Path(str(args.root_hash_payload) + '.json').read_text())
        disk = json.loads(args.virtio_block_image.with_suffix('.json').read_text())
        if (evidence['build'] != '25F71' or evidence['component'] != 'BaseSystemVolume'
                or not evidence['manifest_digest_matches']
                or evidence['payload_sha256'] != hashlib.sha256(root_hash).hexdigest()
                or evidence['payload_bytes'] != len(root_hash)
                or evidence['raw_disk_sha256'] != disk['sha256']):
            raise ValueError('root hash does not belong to the paired disk')
        with args.virtio_block_image.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != disk['sha256']:
                raise ValueError('actual disk differs from its root-hash input evidence')
        record['root_hash_input'] = evidence
    checkpoint = addresses['_' + args.checkpoint]
    if args.decode_existing_snapshot:
        saved = json.loads((args.output / 'kernel-layout.json').read_text())
        snapshot = json.loads((args.output / 'gdb-stop.json').read_text())
        if (saved['uuid'] != record['uuid'] or snapshot['kernel_sha256'] != record['kernel_sha256']):
            raise ValueError('saved snapshot differs from this kernel build')
        record = saved
        instruction_request = f'{checkpoint:x}:10'
        log_requests = []
        if '_sheng_log_buffer' in addresses:
            from decode_native_log import SIZE
            base = addresses['_sheng_log_buffer']
            log_requests = [f'{base + offset:x}:{min(4096, SIZE - offset):x}'
                            for offset in range(0, SIZE, 4096)]
        panic_requests = ([f'{addresses["_gPanicBase"]:x}:{offset:x}:1000'
                           for offset in range(0, 524288, 4096)]
                          if args.capture_panic_buffer else [])
        cpu_handler_request = (f'{addresses["_CpuDataEntries"] + 8:x}:d8:8'
                               if '_CpuDataEntries' in addresses else None)
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / 'kernel-layout.json').write_text(json.dumps(record, indent=2) + '\n')
        pin = json.loads((ROOT / 'config/sheng-reconstructed-inputs.json').read_text())
        inputs = ROOT / 'private/build-inputs' / (pin['release'] + '-extracted')
        esp = args.output / 'esp'
        payload = esp / 'EFI/UniXNU/Payloads'
        payload.mkdir(parents=True)
        (esp / 'EFI/BOOT').mkdir()
        shutil.copy2(inputs / 'loader/BOOTAA64.EFI', esp / 'EFI/BOOT/BOOTAA64.EFI')
        loader = json.loads(args.loader_build.read_text())
        if record['architecture'] == 'arm64e' and not loader.get('native_arm64e_supported'):
            raise ValueError('ARM64E observation requires the loader with architectural PAC admission')
        loader_path = ROOT / loader['file']
        if loader.get('native_panic_region_bytes') != 524288 or loader.get('bootstrap_block_bytes') != 33554432 or hashlib.sha256(loader_path.read_bytes()).hexdigest() != loader['sha256']:
            raise ValueError('native kernel needs the built 32 MiB-congruent DarwinBoot loader')
        shutil.copy2(loader_path, payload / 'DarwinBoot.efi')
        record['loader_sha256'] = loader['sha256']
        shutil.copy2(kernel, payload / 'kernel.macho')
        boot_args = NATIVE_BOOT_ARGS
        if args.qemu_no_ignition:
            if '_sheng_qemu_no_ignition_enabled' not in addresses:
                raise ValueError('kernel lacks the guarded QEMU skipIgnition path')
            boot_args += ' -sheng-qemu-no-ignition'
        record['qemu_no_ignition'] = args.qemu_no_ignition
        if args.kext_log is not None:
            boot_args += f' kextlog={args.kext_log:#x}'
        if args.early_console:
            boot_args += ' -sheng-early-console'
        if args.handoff_pause:
            if not loader.get('handoff_panic_address_visible'):
                raise ValueError('handoff capture needs the loader with visible panic PA')
            boot_args += ' -sheng-capture-handoff'
        record['boot_args'] = boot_args
        (esp / 'EFI/UniXNU/unixnu.toml').write_text(
            'version = 1\n[boot]\ntimeout = 1\ndefault = "native26"\n'
            '[kits]\nautoload = false\n[[driver]]\npath = "Payloads/DarwinBoot.efi"\n'
            '[[entry]]\nid = "native26"\ntitle = "Native SHENG macOS 26 - kernel entry"\n'
            'type = "xnu"\npath = "Payloads/kernel.macho"\n'
            f'args = "{boot_args}"\n')
        dt_command = [sys.executable, ROOT / 'UniXNU/scripts/qemu-entry/make-dt.py',
                        '--output', payload / 'kernel.macho.adt', '--dram-size', '0x40000000',
                        '--owned-memory-size', '0x20000000', '--panic-log', '--armvirt', '--armcpu',
                        '--platform-compatible', 'xiaomi,sheng', '--qemu-vmm-present',
                        '--nvram-proxy', '--crypto-hash-method', 'sha2-384',
                        '--amfi-platform-only', '--random-seed-bytes', str(args.seed_bytes)]
        if args.virtio_block_image:
            disk = args.virtio_block_image.resolve()
            if not disk.is_file() or not disk.stat().st_size or disk.stat().st_size % 512:
                raise ValueError('requires a sector-aligned existing raw disk')
            fdt = args.output.resolve() / 'qemu-block.dtb'
            subprocess.run(['qemu-system-aarch64', '-M',
                f'virt,virtualization=off,secure=off,gic-version=3,dumpdtb={fdt}',
                '-cpu', 'cortex-a710', '-m', '1024', '-smp', '1', '-nic', 'none', '-display', 'none',
                '-global', 'virtio-mmio.force-legacy=false', '-blockdev', json.dumps(dict(
                    driver='raw', **{'node-name': 'root-disk', 'read-only': True}, file=dict(
                        driver='file', filename=str(disk), **{'read-only': True, 'locking': 'off'}))),
                '-device', 'virtio-blk-device,drive=root-disk'], check=True, timeout=30)
            dt_command += ['--virtio-mmio-fdt', str(fdt)]
            if args.root_volume_uuid:
                dt_command += ['--root-match-volume-uuid', str(args.root_volume_uuid)]
        subprocess.run(dt_command, check=True)
        configure_native_text_state(payload / 'kernel.macho.adt',
                                    development_root=args.qemu_development_root, root_hash=root_hash)
        record['qemu_development_root'] = args.qemu_development_root
        record['kernel_ctrr_to_be_enabled'] = 0
        command = [sys.executable, ROOT / 'UniXNU/scripts/qemu-entry/gdb-stop.py', hex(checkpoint),
                   '--fixture', args.output, '--esp', esp, '--kernel', kernel,
                   '--firmware', args.firmware.resolve(), '--gic-version', '3',
                   '--qemu-memory-mib', '1024', '--timeout', str(args.timeout),
                   '--system-registers', '--qemu-ramfb']
        if args.trace_init_syscalls:
            command += ['--arm64-saved-state-count', '74' if record['architecture'] == 'arm64e' else '72',
                        '--syscall-start-address', hex(addresses['_load_init_program']),
                        '--syscall-log-address', hex(addresses['_unix_syscall']),
                        '--syscall-log-address', hex(addresses['_mach_syscall'])]
        if args.follow_init_entry:
            command += ['--follow-entrypoint-arg', '1']
            if launchd_main is not None:
                command += ['--follow-main-entry-offset', str(launchd_main)]
            else:
                command += ['--step-followed-entry', '16']
        if not args.let_vector_log:
            command += ['--also-stop', hex(addresses['_panic'])]
        if args.capture_screen:
            command += ['--capture-screen']
        if args.virtio_block_image:
            command += ['--virtio-block-image', str(args.virtio_block_image.resolve())]
        (args.output / 'command.json').write_text(json.dumps([str(x) for x in command], indent=2) + '\n')
        vector_base = addresses['_ExceptionVectorsBase']
        if not args.let_vector_log:
            for offset in (0, 0x200, 0x400, 0x600):
                command += ['--also-stop', hex(vector_base + offset)]
        command += ['--read-memory', f'{vector_base:x}:800']
        instruction_request = f'{checkpoint:x}:10'
        command += ['--read-memory', instruction_request]
        for name, count in (('_physmap_base', 8), ('_physmap_end', 8), ('_gPhysBase', 8),
                            ('_gPhysSize', 8), ('_segLOWEST', 8), ('_end_kern', 8),
                            ('_ptov_index', 4), ('_ptov_table', 192), ('_const_boot_args', 1152),
                            ('_sheng_corecrypto_status', 4), ('_g_crypto_funcs', 8), ('_prng_ready', 4),
                            ('_img4if', 8), ('_amfi', 8), ('_libCoreEntitlements', 8),
                            ('_pthread_functions', 8), ('_csr_config', 4), ('_dyld_flags', 8),
                        ('_sheng_qemu_no_ignition_enabled', 4),
                            ('_native_virtio_ready', 4), ('_native_virtio_read_requests', 4),
                            ('_native_virtio_read_failures', 4), ('_native_virtio_sectors', 8),
                            ('_native_virtio_mmio_physical', 8), ('_native_virtio_first_sector_sha256', 32),
                            ('_sheng_native_crypto_kmod', 8),
                            ('_sheng_native_crypto_state', 4),
                            ('_armdt_platform_configured', 4), ('_armdt_platform_cpu_count', 4),
                            ('_armdt_platform_device_count', 4), ('_armdt_platform_nvram_proxy', 4),
                            ('_armcpu_registered', 4), ('_armcpu_gic_ready', 4),
                            ('_armcpu_timer_interrupts', 8),
                            ('_gPanicBase', 8), ('_gPanicSize', 4),
                            ('_sheng_early_exception_record', 192),
                            ('_sheng_bootstrap_fb_trace_ready', 8),
                            ('_sheng_bootstrap_c_stage', 8),
                            ('_sheng_bootstrap_vm_stage', 8), ('_sheng_bootstrap_vm_pixels', 8),
                            ('_sheng_bootstrap_vm_witness', 8),
                            ('_sheng_panel_ready', 8), ('_sheng_panel_characters', 8), ('_sheng_panel_witness', 8),
                            ('_sheng_status_witness', 8), ('_sheng_status_message', 45),
                            ('_sheng_status_pixels', 8), ('_sheng_status_row_pa', 8), ('_sheng_status_scale', 8),
                            ('_sheng_console_columns', 8), ('_sheng_first_sync_displayed', 8),
                            ('_sheng_bootstrap_capture_enabled', 4)):
            if name in addresses:
                command += ['--read-memory', f'{addresses[name]:x}:{count:x}']
        cpu_handler_request = None
        if '_CpuDataEntries' in addresses:
            cpu_handler_request = f'{addresses["_CpuDataEntries"] + 8:x}:d8:8'
            command += ['--read-indirect', cpu_handler_request]
        log_requests = []
        if '_sheng_log_buffer' in addresses:
            from decode_native_log import SIZE
            base = addresses['_sheng_log_buffer']
            for offset in range(0, SIZE, 4096):
                request = f'{base + offset:x}:{min(4096, SIZE - offset):x}'
                log_requests.append(request)
                command += ['--read-memory', request]
            (args.output / 'command.json').write_text(json.dumps([str(x) for x in command], indent=2) + '\n')
        panic_requests = []
        if args.capture_panic_buffer:
            if loader.get('native_panic_region_bytes') != 524288 or '_gPanicBase' not in addresses:
                raise ValueError('panic capture requires the loader-owned 512 KiB panic region')
            for offset in range(0, 524288, 4096):
                request = f'{addresses["_gPanicBase"]:x}:{offset:x}:1000'
                panic_requests.append(request)
                command += ['--read-indirect', request]
        (args.output / 'command.json').write_text(json.dumps([str(x) for x in command], indent=2) + '\n')
        with (args.output / 'observer.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    snapshot = json.loads((args.output / 'gdb-stop.json').read_text())
    if log_requests:
        from decode_native_log import decode
        raw = b''.join(bytes.fromhex(snapshot['memory'][key]) for key in log_requests)
        (args.output / 'console.bin').write_bytes(raw)
        try:
            text, console = decode(raw, record['uuid'])
        except ValueError as error:
            text, console = b'', dict(decoded=False, error=str(error))
        (args.output / 'console.txt').write_bytes(text)
        (args.output / 'console.json').write_text(json.dumps(console, indent=2) + '\n')
    if panic_requests:
        pieces = [snapshot['indirect_memory'][key] for key in panic_requests]
        if all('bytes' in piece and not piece['bytes'].startswith('E') for piece in pieces):
            raw = b''.join(bytes.fromhex(piece['bytes']) for piece in pieces)
            if len(raw) != 524288:
                raise ValueError('incomplete XNU panic region capture')
            from decode_xnu_panic import save as save_panic
            info = save_panic(args.output, raw, record['uuid'])
            info.update(bytes=len(raw), virtual_base=pieces[0]['pointer'], read_only=True)
        else:
            info = dict(unavailable='gPanicBase not initialized or snapshot read failed')
        (args.output / 'xnu-panic.json').write_text(json.dumps(info, indent=2) + '\n')
    regs = {name: int(value, 16) for name, value in snapshot['system_registers'].items()}
    tcr = regs['TCR_EL1']
    observed_globals = {}
    for name, width in (('_sheng_corecrypto_status', 4), ('_g_crypto_funcs', 8), ('_prng_ready', 4),
                        ('_img4if', 8), ('_amfi', 8), ('_libCoreEntitlements', 8),
                        ('_pthread_functions', 8), ('_csr_config', 4), ('_dyld_flags', 8),
                        ('_sheng_qemu_no_ignition_enabled', 4),
                        ('_native_virtio_ready', 4), ('_native_virtio_read_requests', 4),
                        ('_native_virtio_read_failures', 4), ('_native_virtio_sectors', 8),
                        ('_native_virtio_mmio_physical', 8),
                        ('_sheng_native_crypto_kmod', 8),
                        ('_sheng_native_crypto_state', 4),
                        ('_armdt_platform_configured', 4), ('_armdt_platform_cpu_count', 4),
                        ('_armdt_platform_device_count', 4), ('_armdt_platform_nvram_proxy', 4),
                        ('_armcpu_registered', 4), ('_armcpu_gic_ready', 4),
                        ('_armcpu_timer_interrupts', 8),
                        ('_gPanicBase', 8), ('_gPanicSize', 4),
                        ('_sheng_bootstrap_capture_enabled', 4), ('_sheng_bootstrap_fb_trace_ready', 8),
                        ('_sheng_bootstrap_c_stage', 8),
                        ('_sheng_bootstrap_vm_stage', 8), ('_sheng_bootstrap_vm_pixels', 8),
                        ('_sheng_bootstrap_vm_witness', 8),
                        ('_sheng_panel_ready', 8), ('_sheng_panel_characters', 8), ('_sheng_panel_witness', 8),
                        ('_sheng_status_witness', 8), ('_sheng_status_pixels', 8),
                        ('_sheng_status_row_pa', 8), ('_sheng_status_scale', 8),
                        ('_sheng_console_columns', 8), ('_sheng_first_sync_displayed', 8)):
        if name in addresses:
            key = f'{addresses[name]:x}:{width:x}'
            value = snapshot['memory'].get(key, 'not captured')
            try:
                raw = bytes.fromhex(value)
                if len(raw) != width:
                    raise ValueError('short memory response')
            except ValueError:
                record.setdefault('unavailable_globals', {})[name] = value
                continue
            observed_globals[name] = int.from_bytes(raw, 'little')
    record['observed_globals'] = {name: hex(value) for name, value in observed_globals.items()}
    if args.virtio_block_image:
        record['virtio_block_input'] = snapshot['virtio_block_input']
        record['root_volume_uuid'] = str(args.root_volume_uuid) if args.root_volume_uuid else None
        if '_native_virtio_first_sector_sha256' in addresses:
            key = f'{addresses["_native_virtio_first_sector_sha256"]:x}:20'
            actual = snapshot['memory'][key]
            record['virtio_first_sector_sha256'] = actual
            record['virtio_first_sector_matches'] = (len(actual) == 64 and actual == snapshot['virtio_block_input']['first_sector_sha256'])
    if cpu_handler_request:
        handler = snapshot['indirect_memory'][cpu_handler_request]
        record['boot_cpu_interrupt_handler'] = dict(handler)
    security_report = args.kernel_build / 'security-relink.json'
    if security_report.is_file():
        security = json.loads(security_report.read_text())
        if (security['candidate_sha256'] != record['kernel_sha256']
                or security['native_kernel_uuid'] != record['uuid']):
            raise ValueError('security component map does not belong to the observed kernel')
        owners = {'_g_crypto_funcs': 'com.apple.kec.corecrypto',
                  '_img4if': 'com.apple.security.AppleImage4',
                  '_amfi': 'com.apple.driver.AppleMobileFileIntegrity',
                  '_libCoreEntitlements': 'com.apple.driver.AppleMobileFileIntegrity'}
        if 'com.apple.kec.pthread' in security['modules']:
            owners['_pthread_functions'] = 'com.apple.kec.pthread'
        record['original_component_interfaces'] = {}
        for symbol, owner in owners.items():
            value = observed_globals.get(symbol, 0)
            module = security['modules'][owner]
            mapped = any(segment['va'] <= value < segment['va'] + segment['size']
                         for segment in module['segments'])
            record['original_component_interfaces'][symbol] = dict(
                pointer=hex(value), registered=bool(value), within_original_module=mapped,
                module=owner, module_uuid=module['uuid'])
    if '_sheng_status_message' in addresses:
        key = f'{addresses["_sheng_status_message"]:x}:2d'
        record['mapped_status_text'] = bytes.fromhex(snapshot['memory'][key]).split(b'\0', 1)[0].decode('ascii', errors='replace')
    if '_sheng_bootstrap_capture_enabled' in addresses:
        record['bootstrap_diagnostic_disarmed'] = observed_globals['_sheng_bootstrap_capture_enabled'] == 0
    if '_sheng_early_exception_record' in addresses:
        key = f'{addresses["_sheng_early_exception_record"]:x}:c0'
        raw = bytes.fromhex(snapshot['memory'][key])
        values = struct.unpack('<24Q', raw)
        names = ('state', 'elr', 'esr', 'far', 'spsr', 'sctlr', 'tcr', 'ttbr0',
                 'ttbr1', 'mair', 'sp', 'mpidr', 'boot_args', 'lr', 'x22', 'x23', 'x24', 'x25',
                 'kernel_va', 'kernel_pa', 'bootstrap_ttbr0', 'physical_fault_entry', 'original_boot_args', 'bootstrap_stage')
        record['early_exception'] = {name: hex(value) for name, value in zip(names, values)}
        (args.output / 'early-exception.bin').write_bytes(raw)
    record['source_crypto_initialized'] = (observed_globals.get('_sheng_corecrypto_status') == 0
                                          and observed_globals.get('_prng_ready') == 1
                                          and bool(observed_globals.get('_g_crypto_funcs')))
    record['full_component_crypto_abi_qualified'] = False
    kernel_data = kernel.read_bytes()
    kernel_image = macho(kernel_data)
    instruction_at = backed_offset(kernel_image['segments'], checkpoint, 16, len(kernel_data))
    instruction_match = snapshot['memory'][instruction_request] == kernel_data[instruction_at:instruction_at + 16].hex()
    record['checkpoint_instructions_match'] = instruction_match
    record['bootloader_entropy_bytes'] = args.seed_bytes
    passed = (instruction_match and not snapshot['bounded_timeout_interrupted'] and int(snapshot['pc'], 16) == checkpoint
              and tcr >> 14 & 3 == 2 and tcr >> 30 & 3 == 1
              and tcr & 63 == 17 and tcr >> 16 & 63 == 17 and regs['SCTLR_EL1'] & 1)
    if args.follow_init_entry:
        entry = snapshot.get('followed_user_entry', {})
        record['followed_init_entry'] = entry
        passed = (instruction_match and entry.get('observed') is True
                  and int(entry.get('pstate', '0xf'), 16) & 15 == 0)
        record['userland_started'] = bool(passed)
        record['el0_steps_observed'] = sum(int(step['pstate'], 16) & 15 == 0
                                            for step in entry.get('steps', []))
        if args.follow_launchd_main:
            main = snapshot.get('followed_main_entry', {})
            record['launchd_main'] = main
            record['launchd_main_started'] = (main.get('observed') is True
                and main.get('first_instruction_completed') is True
                and int(main.get('pstate', '0xf'), 16) & 15 == 0)
            passed = passed and record['launchd_main_started']

    record.update(checkpoint=args.checkpoint, checkpoint_va=hex(checkpoint),
                  reached=bool(passed), snapshot='gdb-stop.json')
    (args.output / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    if not passed:
        raise RuntimeError('kernel did not reach the requested checkpoint with 16K / 47-bit translation; inspect saved registers')
    print(f'PASS {args.checkpoint}: actual native kernel, 16K / 47-bit translation; QEMU only')


if __name__ == '__main__':
    main()
