#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
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

from observe_macos26_kernel import identify, ROOT, NATIVE_BOOT_ARGS
from package_reference_xnu import vendor_dtbs
from native_devtree import configure_native_text_state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--firmware-build', type=Path, required=True)
    parser.add_argument('--backup-dir', type=Path, required=True)
    parser.add_argument('--qemu-observation', type=Path, required=True)
    parser.add_argument('--bootstrap-observation', type=Path,
                        help='same-kernel QEMU bootstrap with sheng framebuffer geometry')
    parser.add_argument('--early-kernel-experiment', action='store_true',
                        help='explicitly package the known Image4 stop as an early hardware experiment')
    args = parser.parse_args()
    kernel, symbols, audit = identify(args.kernel_build.resolve())
    observed = json.loads((args.qemu_observation / 'result.json').read_text())
    panic = json.loads((args.qemu_observation / 'xnu-panic.json').read_text())
    console = (args.qemu_observation / 'console.txt').read_text()
    boot_args = NATIVE_BOOT_ARGS + ' -sheng-early-console -sheng-capture-handoff'
    if (observed['kernel_sha256'] != audit['kernel_sha256'] or observed['uuid'] != audit['uuid']
            or not observed.get('source_crypto_initialized') or observed.get('boot_args') != boot_args
            or 'SHENG: early framebuffer console acquired' not in console):
        raise ValueError('requires this exact kernel with working source crypto and the early console in QEMU')
    if (not args.early_kernel_experiment or not panic.get('complete') or not panic.get('crc_matches')
            or not panic.get('uuid_verified') or panic['kernel_uuid'] != audit['uuid']
            or 'image4 interface not available' not in (args.qemu_observation / 'xnu-panic.txt').read_text()):
        raise ValueError('only the explicit, recorded Image4 stop is admitted for the current hardware experiment')
    if '_sheng_log_buffer' not in symbols:
        raise ValueError('native hardware candidate requires the retained kernel logger')
    if '_sheng_mmu_sync_fault' in symbols and not observed.get('bootstrap_diagnostic_disarmed'):
        raise ValueError('requires this MMU-on diagnostic to disarm after console setup in QEMU')
    native_build = json.loads((kernel.parent / 'build.json').read_text())
    if native_build.get('native_security_candidate') and native_build.get('hardware_admitted') is not True:
        raise ValueError('security prelink candidates are QEMU-only until their native initialization is qualified')
    if '_sheng_status_pixels' in symbols:
        status = observed.get('observed_globals', {})
        if (int(status.get('_sheng_status_pixels', '0x0'), 16) == 0
                or status.get('_sheng_status_scale') not in ('0x1', '0x2')):
            raise ValueError('requires the independent native status panel mapping and valid font scale')
    elif native_build.get('panel_console_source_sha256'):
        panel = observed.get('observed_globals', {})
        if (panel.get('_sheng_panel_ready') != '0x1' or panel.get('_sheng_panel_witness') != '0x1'
                or int(panel.get('_sheng_panel_characters', '0x0'), 16) < 100):
            raise ValueError('requires retained-log panel binding, real glyph readback and printed text in QEMU')
    if '_sheng_status_witness' in symbols:
        if (observed.get('observed_globals', {}).get('_sheng_status_witness') != '0x1'
                or not observed.get('mapped_status_text', '').startswith('PANIC: image4 interface not available')):
            raise ValueError('requires mapped status glyph readback and pinned Image4 panic text in QEMU')
    if '_sheng_console_columns' in symbols:
        panel = observed.get('observed_globals', {})
        if (panel.get('_sheng_panel_ready') != '0x1' or panel.get('_sheng_panel_witness') != '0x1'
                or int(panel.get('_sheng_panel_characters', '0x0'), 16) < 100):
            raise ValueError('requires the pre-console live RAM log mirror to bind and print actual glyphs')
        from PIL import Image
        with Image.open(args.qemu_observation / 'screen.png') as screen:
            pixels = screen.convert('RGB')
            scale = 2 if screen.width >= 960 else 1
            top = 608 if screen.height >= 1024 else 32
            for cell in range(5):
                glyph = pixels.crop((224 + cell * 8 * scale, top,
                                     224 + (cell + 1) * 8 * scale, top + 16 * scale))
                if sum(min(glyph.getpixel((x, y))) >= 220
                       for y in range(glyph.height) for x in range(glyph.width)) < 8 * scale * scale:
                    raise ValueError('actual stopped framebuffer has a blank or overwritten diagnostic title')
    if (native_build.get('bootstrap_c_trace_source_sha256') and
            observed.get('observed_globals', {}).get('_sheng_bootstrap_c_stage') != '0xf'):
        raise ValueError('requires this kernel to complete the early C stage strip in QEMU')
    if native_build.get('bootstrap_vm_trace_source_sha256'):
        vm = observed.get('observed_globals', {})
        if (vm.get('_sheng_bootstrap_vm_stage') != '0xf'
                or int(vm.get('_sheng_bootstrap_vm_pixels', '0x0'), 16) == 0
                or int(vm.get('_sheng_bootstrap_vm_witness', '0x0'), 16) & 0xf800 != 0xf800):
            raise ValueError('requires native I/O mapping and real VM-to-console stage pixel readback in QEMU')
    if (native_build.get('bootstrap_trace_source_sha256') and
            observed.get('early_exception', {}).get('bootstrap_stage') !=
            ('0xf' if native_build.get('bootstrap_post_mmu_stages') else '0xc')):
        raise ValueError('requires this kernel to complete its bootstrap stage strip in QEMU')
    if native_build.get('bootstrap_post_mmu_stages'):
        if args.bootstrap_observation is None:
            raise ValueError('post-MMU stages require a separate sheng-geometry bootstrap observation')
        bootstrap = json.loads((args.bootstrap_observation / 'result.json').read_text())
        # The UEFI QEMU GOP can be smaller than the diagnostic panel.
        if (bootstrap.get('kernel_sha256') != audit['kernel_sha256']
                or bootstrap.get('uuid') != audit['uuid']
                or not bootstrap.get('reached_c_entry')
                or not bootstrap.get('instruction_and_args_match')
                or bootstrap.get('bootstrap_stage') != '0xf'
                or bootstrap.get('post_mmu_framebuffer_mapping_ready') is not True
                or bootstrap.get('actual_stage_pixels') != ['0xff00ff00'] * 16
                or bootstrap.get('hardware_executed') is not False):
            raise ValueError('requires same-kernel C entry and all real stage pixels with sheng geometry')
    firmware = json.loads(args.firmware_build.read_text())
    patch = 'patches/UniXNU/0007-native-16k-bootstrap-congruence.patch'
    panic_patch = 'patches/UniXNU/0009-native-owned-panic-region.patch'
    handoff_patch = 'patches/UniXNU/0012-native-handoff-log-addresses.patch'
    progress_patch = 'patches/UniXNU/0013-native-handoff-progress.patch'
    coherency_patch = 'patches/UniXNU/0014-native-handoff-code-coherency.patch'
    arm64e_patch = 'patches/UniXNU/0011-native-arm64e-loader.patch'
    persistence_patch = 'patches/UniXNU/0015-native-retained-log-persistence.patch'
    if (firmware.get('preflight_only') is not False or firmware.get('native_el1')
            or firmware['bootimg']['compression'] != 'none'
            or firmware.get('patches_sha256', {}).get(persistence_patch) != hashlib.sha256((ROOT / persistence_patch).read_bytes()).hexdigest()
            or firmware.get('patches_sha256', {}).get(panic_patch) != hashlib.sha256((ROOT / panic_patch).read_bytes()).hexdigest()
            or firmware.get('patches_sha256', {}).get(handoff_patch) != hashlib.sha256((ROOT / handoff_patch).read_bytes()).hexdigest()
            or firmware.get('patches_sha256', {}).get(progress_patch) != hashlib.sha256((ROOT / progress_patch).read_bytes()).hexdigest()
            or firmware.get('patches_sha256', {}).get(coherency_patch) != hashlib.sha256((ROOT / coherency_patch).read_bytes()).hexdigest()
            or (audit['architecture'] == 'arm64e' and firmware.get('patches_sha256', {}).get(arm64e_patch)
                != hashlib.sha256((ROOT / arm64e_patch).read_bytes()).hexdigest())
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
                        '--owned-memory-size', '0x20000000', '--panic-log', '--cpu-regs', '0',
                        '--cpu-compatible', 'arm,cortex-a510', '--random-seed-bytes', '256'], check=True)
        configure_native_text_state(files / 'kernel.macho.adt')
        (stage / 'unixnu.toml').write_text(
            'version = 1\n[boot]\ntimeout = 3\ndefault = "native26"\n'
            '[kits]\nautoload = false\n[[entry]]\nid = "native26"\n'
            'title = "SHENG macOS 26 - native kernel with RAM log"\n'
            'type = "xnu"\npath = "Payloads/kernel.macho"\n'
            f'args = "{boot_args}"\n')
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
                      purpose='Early native EL1 kernel experiment; macOS recovery is not ready',
                      expected_stop='image4 interface not available', boot_args=boot_args,
                      qemu_observation=str(args.qemu_observation.resolve()),
                      bootstrap_observation=(str(args.bootstrap_observation.resolve())
                                             if args.bootstrap_observation else None),
                      source_crypto_post_passed=True, security_components_loaded=False,
                      framebuffer_console_qemu_qualified=True, hardware_log_transport_qualified=False,
                      log_symbol_va=hex(symbols['_sheng_log_buffer']),
                      log_physical_address='actual DarwinBoot PA + log_symbol_va - kernel linked base',
                      bootstrap_block_bytes=33554432, owned_memory_bytes=0x20000000,
                      native_panic_region_bytes=524288,
                      handoff_progress='green=entered blue=cache-clean orange=MMU-off',
                      native_early_exception_screen='_sheng_early_exception_record' in symbols,
                      native_mmu_on_exception_screen='_sheng_mmu_sync_fault' in symbols,
                      firmware_sha256=firmware['sha256'], temporary_ram_boot=True,
                      hardware_executed=False, userland_started=False,
                      storage_drivers_linked=False, partition_images_written=False,
                      firmware_log_file_writes_enabled=True,
                      firmware_log_partition="4cd2ed34-2142-4ea4-abf2-ec6c51d117d7",
                      firmware_log_warm_retention_qualified=False)
        (destination / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
        (destination / 'experiment.md').write_text(
            '# sheng 原生内核早期实验\n\n'
            f'内核 UUID：`{audit["uuid"]}`，架构：`{audit["architecture"]}`。\n\n'
            '镜像只用于 RAM 启动，不执行 flash、分区或 Android 槽位切换。\n'
            '部署使用 scripts/boot_native_experiment.py，明确指定实验前确认的 --expected-slot。\n'
            '槽位改变或不可启动时停止；USB 状态不明时不得自动重发。\n'
            '预期到达 Image4 尚未注册的 panic；这不是恢复系统或桌面。\n\n'
            '选择 UniXNU 后，交接页停留 10 秒。拍下 kernel pa 与 panic pa。\n'
            '内核接管后应显示文本控制台，保存最后画面。\n'
            '顶部三条标记：绿色=进入交接汇编，蓝色=缓存清理完成，橙色=MMU关闭后执行。\n'
            '这些标记均来自加载器，不能单独证明XNU已经执行。\n'
            'XNU=1 表示入口已执行；XNU=2 为低位异常，XNU=3 为控制台前 MMU 开启时的同步异常。\n'
            '若显示 XNU=2/3，请拍下 ELR/ESR/FAR 与全部控制寄存器。\n'
            '交接页 MACOSLOG 的 next=Success 表示实际PA恢复请求已写入专用日志卷。\n'
            '随后返回fastboot并再次临时启动同版UniXNU，加载器会先尝试保存上一轮RAM日志。\n'
            '仅向已授权macoslog写普通文件，不修改GPT或刷写分区镜像。\n'
            '跨重启RAM保留尚未实机验收；不可把next=Success当成已恢复日志。\n'
            'root Recovery可用scripts/capture_persistent_log.py只读导出。\n')
        print(destination / image.name)


if __name__ == '__main__':
    main()
