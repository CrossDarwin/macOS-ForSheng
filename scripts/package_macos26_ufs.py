#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Package a qualified native UFS root experiment for temporary sheng RAM boot."""
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
import uuid

from observe_macos26_kernel import identify, ROOT, NATIVE_BOOT_ARGS
from package_reference_xnu import vendor_dtbs
from native_devtree import configure_native_text_state
from build_macos26_storage import PROTOCOL_CHARACTERISTICS


def qualify(build, observation, bootstrap, default_off, installed, plan, root_build):
    kernel, symbols, identity = identify(build)
    kernel_build = json.loads((build / 'build.json').read_text())
    for name in ('0051-native-multiline-panic-panel.patch', '0052-native-independent-panic-surface.patch'):
        panel_patch = ROOT / 'platform/sheng/macos26/patches' / name
        if kernel_build.get('patches', {}).get(str(panel_patch.relative_to(ROOT))) != hashlib.sha256(panel_patch.read_bytes()).hexdigest():
            raise ValueError('requires the compiled independent multiline panic panel')
    observed = json.loads((observation / 'result.json').read_text())
    geometry = observed.get('observed_globals', {})
    normal_rows = int(geometry.get('_sheng_console_rows', '0x0'), 16)
    traced = json.loads((bootstrap / 'result.json').read_text())
    refused = json.loads((default_off / 'gdb-stop.json').read_text())
    relink = json.loads((build / 'security-relink.json').read_text())
    media = json.loads(installed.read_text())
    partition = json.loads(plan.read_text())
    root = json.loads(root_build.read_text())
    if (observed.get('kernel_sha256') != identity['kernel_sha256']
            or observed.get('uuid') != identity['uuid'] or observed.get('reached') is not True
            or observed.get('checkpoint') != 'IOFindBSDRoot'
            or observed.get('source_crypto_initialized') is not True
            or observed.get('bootstrap_diagnostic_disarmed') is not True
            or observed.get('observed_globals', {}).get('_sheng_panel_ready') != '0x1'
            or not 6 <= normal_rows <= 24
            or geometry.get('_sheng_panel_bound_rows') != geometry.get('_sheng_console_rows')
            or observed.get('observed_globals', {}).get('_sheng_panic_panel_bound_rows') != '0x10'
            or observed.get('observed_globals', {}).get('_sheng_panel_witness') != '0x1'):
        raise ValueError('requires this exact native kernel at the qualified root-discovery checkpoint')
    for name in ('_g_crypto_funcs', '_img4if', '_amfi', '_libCoreEntitlements', '_pthread_functions'):
        interface = observed.get('original_component_interfaces', {}).get(name, {})
        if interface.get('registered') is not True or interface.get('within_original_module') is not True:
            raise ValueError('missing original startup interface: ' + name)
    if (traced.get('kernel_sha256') != identity['kernel_sha256'] or traced.get('uuid') != identity['uuid']
            or traced.get('reached_c_entry') is not True or traced.get('instruction_and_args_match') is not True
            or traced.get('bootstrap_stage') != '0xf'
            or traced.get('post_mmu_framebuffer_mapping_ready') is not True
            or traced.get('actual_stage_pixels') != ['0xff00ff00'] * 16):
        raise ValueError('requires matching sheng physical-placement and framebuffer bootstrap execution')
    driver = relink['storage_driver']
    recovery = json.loads((ROOT / 'config/macos26-recovery-root.json').read_text())
    if (relink.get('candidate_sha256') != identity['kernel_sha256']
            or driver['bundle'] != 'org.blu-sharky.NativeUfs'
            or driver['build'].get('root_partition') != 'macosroot'
            or driver['build'].get('root_lun') != 0
            or driver['build'].get('android_userdata_used') is not False
            or driver['build'].get('recovery_root') != recovery
            or driver['build'].get('recovery_disk_image_protocol') != PROTOCOL_CHARACTERISTICS
            or driver['build'].get('recovery_transport_is_not_authentication') is not True
            or driver['vtable_abi'].get('block_class') != 'NativeUfsBlock'
            or driver['vtable_abi'].get('pac_metadata_matches') is not True
            or not 1 <= driver['vtable_abi'].get('slots', 0) <= 512
            or refused.get('kernel_sha256') != identity['kernel_sha256']
            or refused.get('function_return_stack_matched') is not True or refused.get('x0') != '0x0'):
        raise ValueError('requires the paired recovery UFS ABI and actual default-off function return')
    for name in ('_native_ufs_probe_requested', '_native_ufs_mapped', '_native_ufs_root_step', '_native_ufs_blocks_published'):
        address = driver['symbols'][name]
        if refused['memory'].get(f'{address:x}:4') != '00000000':
            raise ValueError('UFS default-off runtime touched hardware or published media')
    if (media.get('status') != 'verified' or media.get('readback_verified') is not True
            or media.get('destination') != '/dev/block/by-name/macosroot'
            or media.get('destination_guid') != partition.get('root_unique_guid')
            or media.get('sha256') != media.get('readback_sha256')
            or partition.get('applied') is not True or partition.get('root_image_readback_verified') is not True
            or partition.get('root_image_sha256') != media['sha256']
            or media.get('bytes') != root.get('image_bytes') or root.get('build') != '25F71'
            or media.get('bytes', 0) > partition.get('root_bytes', 0)
            or len(root.get('windows', [])) != 1
            or any(root['windows'][0].get(k) != recovery[k] for k in ('bytes', 'sha256'))
            or root['windows'][0].get('name') != recovery['window']):
        raise ValueError('requires the written dedicated root extent with matching full readback')
    return kernel, symbols, identity, media, partition


def qualify_development_dyld(build, observation, identity, root_uuid):
    patch = ROOT / 'platform/sheng/macos26/patches/0053-development-dyld-commpage.patch'
    compiled = json.loads((build / 'build.json').read_text())
    if compiled.get('patches', {}).get(str(patch.relative_to(ROOT))) != hashlib.sha256(patch.read_bytes()).hexdigest():
        raise ValueError('requires the compiled explicit development dyld path')
    observed = json.loads((observation / 'result.json').read_text())
    globals_ = observed.get('observed_globals', {})
    if (observed.get('uuid') != identity['uuid']
            or observed.get('kernel_sha256') != identity['kernel_sha256']
            or observed.get('development_no_ignition') is not True
            or observed.get('qemu_no_ignition') is not False
            or globals_.get('_sheng_development_no_ignition_enabled') != '0x1'
            or globals_.get('_sheng_qemu_no_ignition_enabled') != '0x0'
            or not int(observed.get('actual_commpage_dyld_flags', '0x0'), 16) & 8
            or observed.get('root_volume_uuid') != str(root_uuid)
            or observed.get('userland_started') is not True
            or observed.get('launchd_main_started') is not True):
        raise ValueError('requires matching development commpage and original launchd main execution')
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--qemu-observation', type=Path, required=True)
    parser.add_argument('--bootstrap-observation', type=Path, required=True)
    parser.add_argument('--default-off-observation', type=Path, required=True)
    parser.add_argument('--root-deployment', type=Path, required=True)
    parser.add_argument('--partition-plan', type=Path, required=True)
    parser.add_argument('--root-build', type=Path, required=True)
    parser.add_argument('--root-hash', type=Path, required=True)
    parser.add_argument('--root-volume-uuid', type=uuid.UUID, required=True)
    parser.add_argument('--firmware-build', type=Path, required=True)
    parser.add_argument('--backup-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--development-no-ignition', action='store_true')
    parser.add_argument('--dyld-observation', type=Path,
                        help='matching original launchd main execution with the explicit development flag')
    args = parser.parse_args()
    if args.development_no_ignition != bool(args.dyld_observation):
        parser.error('--development-no-ignition and --dyld-observation must be used together')
    kernel, symbols, identity, media, partition = qualify(args.kernel_build,
        args.qemu_observation, args.bootstrap_observation, args.default_off_observation,
        args.root_deployment, args.partition_plan, args.root_build)
    root_hash = args.root_hash.read_bytes()
    hash_evidence = json.loads(args.root_hash.with_suffix(args.root_hash.suffix + '.json').read_text())
    root = json.loads(args.root_build.read_text())
    recovery = json.loads((ROOT / 'config/macos26-recovery-root.json').read_text())
    if args.root_volume_uuid != uuid.UUID(recovery['volume_uuid']):
        raise ValueError('root UUID differs from the compiled recovery transport')
    if (hash_evidence.get('build') != '25F71' or hash_evidence.get('manifest_digest_matches') is not True
            or hash_evidence.get('payload_sha256') != hashlib.sha256(root_hash).hexdigest()
            or hash_evidence.get('raw_disk_sha256') != root['windows'][0]['sha256']):
        raise ValueError('root-hash payload does not belong to the installed BaseSystem')
    firmware = json.loads(args.firmware_build.read_text())
    required = ('0007-native-16k-bootstrap-congruence', '0011-native-arm64e-loader',
                '0013-native-handoff-progress', '0014-native-handoff-code-coherency',
                '0015-native-retained-log-persistence', '0033-retained-log-high-bank-and-filesystem')
    for name in required:
        patch = ROOT / ('patches/UniXNU/' + name + '.patch')
        if firmware.get('patches_sha256', {}).get(str(patch.relative_to(ROOT))) != hashlib.sha256(patch.read_bytes()).hexdigest():
            raise ValueError('firmware lacks the pinned loader contract: ' + name)
    if firmware.get('preflight_only') is not False or firmware.get('native_el1') or firmware['bootimg']['compression'] != 'none':
        raise ValueError('requires the qualified normal sheng firmware container')
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
        raise ValueError('requires backed-up slot A OS metadata')
    os_version = struct.unpack_from('<I', boot, 16)[0]
    geometry = tomllib.loads((ROOT / 'uefi-sheng/Resources/Configs/sheng.toml').read_text())['boot_image']
    if not os_version or geometry['header_version'] != 0:
        raise ValueError('requires the qualified v0 transport and stock version field')
    boot_args = NATIVE_BOOT_ARGS + ' -sheng-early-console -sheng-capture-handoff native-ufs-root=1 native-ufs-diagnostics=1'
    if args.development_no_ignition:
        qualify_development_dyld(args.kernel_build, args.dyld_observation, identity, args.root_volume_uuid)
        boot_args += ' -sheng-development-no-ignition'
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(dir=args.output) as temporary:
            work = Path(temporary)
            stage = work / 'EFI/UniXNU'
            files = stage / 'Payloads'
            files.mkdir(parents=True)
            shutil.copy2(kernel, files / 'kernel.macho')
            subprocess.run(['python3', ROOT / 'UniXNU-sheng/scripts/make-sheng-adt.py',
                '--output', files / 'kernel.macho.adt', '--dram-size', '0x200000000',
                '--owned-memory-size', '0xc0000000', '--panic-log', '--cpu-regs', '0',
                '--cpu-compatible', 'arm,cortex-a510', '--random-seed-bytes', '256',
                '--os-environment', 'recoveryos',
                '--root-match-volume-uuid', str(args.root_volume_uuid)], check=True)
            configure_native_text_state(files / 'kernel.macho.adt', development_root=True,
                                        root_hash=root_hash, boot_volume_uuid=args.root_volume_uuid)
            (stage / 'unixnu.toml').write_text('version = 1\n[boot]\ntimeout = -1\nfallback_timeout = 30\ndefault = "native26ufs"\n'
                '[kits]\nautoload = false\n[[entry]]\nid = "native26ufs"\n'
                f'title = "SHENG macOS 26 - UFS {identity["uuid"][:8]}"\ntype = "xnu"\n'
                'path = "Payloads/kernel.macho"\nargs = "' + boot_args + '"\n')
            content = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())
            mib = max(64, ((content * 5 // 4 + (1 << 20) - 1) >> 20) + 8)
            if mib > 192:
                raise ValueError('candidate exceeds the bounded RAM FAT budget')
            fat = work / 'native.fat'
            subprocess.run(['mformat', '-C', '-F', '-T', str(mib * 2048), '-v', 'SHENGXNU26',
                            '-N', '53484e26', '-i', fat, '::'], check=True)
            subprocess.run(['mcopy', '-i', fat, '-s', '-Q', work / 'EFI', '::/'], check=True)
            transport = work / 'Image-dtb'
            transport.write_bytes(gzip.compress(payload, mtime=0) + vendor_dtbs(args.backup_dir / 'vendor_boot_a.img'))
            image = work / 'sheng-macos26-kernel.img'
            command = ['python3', ROOT / 'uefi-sheng/Resources/Scripts/mkbootimg.py',
                       '--kernel', transport, '--ramdisk', fat, '-o', image]
            for name in ('base', 'kernel_offset', 'tags_offset', 'pagesize', 'header_version'):
                command += ['--' + name, str(geometry[name])]
            subprocess.run(command, check=True)
            data = bytearray(image.read_bytes())
            struct.pack_into('<I', data, 44, os_version)
            (args.output / image.name).write_bytes(data)
            shutil.copy2(files / 'kernel.macho.adt', args.output / 'kernel.macho.adt')
            record = dict(container_sha256=hashlib.sha256(data).hexdigest(), container_bytes=len(data),
                kernel=identity, purpose='Native EL1 UFS root experiment; hardware execution unqualified',
                boot_args=boot_args, temporary_ram_boot=True, partition_images_written=False,
                root_media_preinstalled=True, root_partition_guid=partition['root_unique_guid'],
                root_image_sha256=media['sha256'], root_volume_uuid=str(args.root_volume_uuid),
                owned_memory_bytes=0xc0000000, native_panic_region_bytes=524288,
                source_crypto_post_passed=True, original_interfaces_qemu_registered=True,
                ufs_vtable_qualified=True, ufs_default_off_qemu_qualified=True,
                ufs_hardware_read_qualified=False, userland_started=False,
                qemu_observation=str(args.qemu_observation.resolve()),
                bootstrap_observation=str(args.bootstrap_observation.resolve()),
                default_off_observation=str(args.default_off_observation.resolve()),
                hardware_log_transport_qualified=False, firmware_sha256=firmware['sha256'],
                log_symbol_va=hex(symbols['_sheng_log_buffer']),
                firmware_log_partition='4cd2ed34-2142-4ea4-abf2-ec6c51d117d7',
                firmware_log_repair=dict(high_bank=['0x8c0000000', '0xa00000000'],
                    partition_bound_fat_connect=True, status_files=['ARM.BIN', 'RECOVERY.BIN'],
                    patch_sha256=firmware['patches_sha256']['patches/UniXNU/0033-retained-log-high-bank-and-filesystem.patch'],
                    warm_reboot_capture_qualified=False),
                development_root=True, synthetic_vm_identity=False, qemu_only_boot_args=False,
                development_no_ignition=args.development_no_ignition,
                dyld_observation=str(args.dyld_observation.resolve()) if args.dyld_observation else None,
                root_variant='recoveryos', recovery_transport_is_not_authentication=True,
                deployment_scope='fastboot boot only; no boot/recovery/UEFI partition flashing')
            (args.output / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
            print(args.output / image.name)
    except BaseException:
        # Remove only the failed package in the newly created directory; preserve symbols and existing images.
        shutil.rmtree(args.output)
        raise


if __name__ == '__main__':
    main()
