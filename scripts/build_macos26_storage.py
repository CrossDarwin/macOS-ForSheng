#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build pinned native transports against the paired macOS storage headers."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import uuid

from native_macho import macho
from native_log_file import validate_contract

BUNDLE = 'org.unixnu.driver.NativeVirtioBlock'
PROTOCOL_CHARACTERISTICS = {
    'Physical Interconnect': 'Virtual Interface',
    'Physical Interconnect Location': 'External',
}


def build(root, out, compile_record, source, run, record, env, *, transport='virtio', gop_display=False):
    if transport not in ('virtio', 'ufs'):
        raise ValueError('unsupported native storage transport')
    if gop_display and transport != 'ufs':
        raise ValueError('the board GOP companion requires the UFS bundle')
    component = 'NativeVirtioBlock' if transport == 'virtio' else 'NativeUfs'
    bundle = BUNDLE if transport == 'virtio' else 'org.blu-sharky.NativeUfs'
    directory = 'storage-driver' if transport == 'virtio' else 'ufs-driver'
    destination = out / directory
    destination.mkdir(exist_ok=True)
    display = None
    if gop_display:
        from prepare_macos26_gop import prepare
        display = prepare(root, destination / 'gop-display')
    upstream = root / 'UniXNU/drivers' / component / (component + '.cpp')
    include = destination / 'include/IOKit/storage'
    include.mkdir(parents=True, exist_ok=True)
    for header in (root / 'sources/macos26/IOStorageFamily').glob('*.h'):
        (include / header.name).write_bytes(header.read_bytes())
    wrapper = destination / (component + '.cpp')
    entry_prefix = 'sheng_virtio' if transport == 'virtio' else 'sheng_ufs'
    recovery_prefix = ''
    recovery_root = None
    if transport == 'ufs':
        recovery_root = json.loads((root / 'config/macos26-recovery-root.json').read_text())
        digest = bytes.fromhex(recovery_root['sha256'])
        identity = str(uuid.UUID(recovery_root['volume_uuid'])).upper()
        if (recovery_root['build'] != '25F71' or recovery_root['variant'] != 'recoveryos'
                or recovery_root['window'] != 'OS' or len(digest) != 32
                or recovery_root['bytes'] <= 0 or recovery_root['bytes'] % 512):
            raise ValueError('requires the paired read-only recovery root contract')
        recovery_prefix = ('#include <libkern/libkern.h>\n'
            f'#define NATIVE_UFS_RECOVERY_BYTES {recovery_root["bytes"]}ULL\n'
            '#define NATIVE_UFS_RECOVERY_DIGEST {' + ','.join(str(b) for b in digest) + '}\n'
            f'#define NATIVE_UFS_RECOVERY_UUID "{identity}"\n')
        if 'isc' in recovery_root:
            isc = recovery_root['isc']
            isc_digest = bytes.fromhex(isc['sha256'])
            isc_uuid = str(uuid.UUID(isc['volume_uuid'])).upper()
            if (isc['window'] != 'ISC' or len(isc_digest) != 32 or not 0 < isc['bytes'] <= 4 << 30
                    or isc['bytes'] % 4096 or isc['volatile_overlay_limit_bytes'] != 64 << 20
                    or isc['sep_trusted_storage'] is not False):
                raise ValueError('requires the bounded owned ISC seed contract')
            recovery_prefix += (f'#define NATIVE_UFS_ISC_BYTES {isc["bytes"]}ULL\n'
                '#define NATIVE_UFS_ISC_DIGEST {' + ','.join(str(b) for b in isc_digest) + '}\n'
                f'#define NATIVE_UFS_ISC_UUID "{isc_uuid}"\n')
        recovery_prefix += f'#include "{root / "platform/sheng/macos26/storage/recovery_root.h"}"\n'
        log = json.loads((root / 'config/macoslog.json').read_text())
        validate_contract(log)
        recovery_prefix += '#define NATIVE_MACOSLOG 1\n'
        for name, value in (('FILE', uuid.UUID(log['file_uuid']).bytes),
                            ('PARTITION', uuid.UUID(log['partition_uuid']).bytes_le),
                            ('TYPE', uuid.UUID(log['partition_type']).bytes_le)):
            recovery_prefix += '#define NATIVE_MACOSLOG_' + name + '_ID {' + ','.join(map(str, value)) + '}\n'
        recovery_prefix += f'#define NATIVE_MACOSLOG_WORKER "{root / "platform/sheng/macos26/storage/macoslog_worker.h"}"\n'
    wrapper.write_text(
        '#include <TargetConditionals.h>\n'
        'static_assert(TARGET_OS_OSX == 1, "requires macOS storage ABI");\n'
        + recovery_prefix +
        f'#include "{upstream}"\n' +
        (f'#include "{display["source"]}"\n' if display else '') +
        '#include <mach/kmod.h>\n'
        f'extern "C" kern_return_t {entry_prefix}_start(kmod_info_t *, void *) {{ return KERN_SUCCESS; }}\n'
        f'extern "C" kern_return_t {entry_prefix}_stop(kmod_info_t *, void *) {{ return KERN_FAILURE; }}\n'
        f'KMOD_EXPLICIT_DECL({bundle}, "1.0.0", {entry_prefix}_start, {entry_prefix}_stop)\n')
    obj = destination / (component + '.o')
    arguments = compile_record['arguments']
    command, index = [], 0
    while index < len(arguments):
        arg = arguments[index]
        if arg == compile_record['file']:
            command.append(str(wrapper))
        elif arg in ('-o', '-MF', '-MT', '-MQ', '-MJ'):
            if arg == '-o':
                command += ['-o', str(obj)]
            index += 1
        elif arg == '-Xclang' and arguments[index + 1].startswith('-W'):
            index += 1
        elif arg.startswith('-W'):
            pass
        elif arg not in ('-MMD', '-MD', '-MP'):
            command.append(arg)
        index += 1
    command[1:1] = ['-I', str(destination / 'include')]
    if transport == 'virtio':
        command[1:1] = ['-DNATIVE_QEMU_SCRATCH_BLOCK=1']
    else:
        command[1:1] = ['-DNATIVE_UFS_ROOT_PARTITION_NAME="macosroot"']
    sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
    command += ['-I', str(source / 'osfmk'), '-I', str(sdk / 'usr/include'),
                '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                '-Wno-c99-designator', '-Wno-reorder-init-list',
                '-Wno-deprecated-enum-enum-conversion', '-Wno-unnecessary-virtual-specifier']
    run(command, directory + '-compile', record, cwd=Path(compile_record['directory']), env=env)
    binary = destination / (component + '.macho')
    run(['xcrun', 'ld', '-arch', 'arm64e', '-kext', '-kexts_use_stubs',
         '-platform_version', 'macos', '26.5', '26.5',
         '-undefined', 'dynamic_lookup', '-fixup_chains',
         '-no_adhoc_codesign', '-headerpad', '0x1000',
         str(obj), '-o', str(binary)], directory + '-link', record, env=env)
    image = macho(binary.read_bytes(), 'arm64e')
    if (image['kind'] != 11 or not image['subtype'] & 0x40000000
            or not any(c == 0x80000034 for c, _, _ in image['commands'])):
        raise ValueError('standalone transport requires an ARM64E bundle with chained imports')
    info = dict(CFBundleIdentifier=bundle, CFBundleVersion='1.0.0',
                CFBundlePackageType='KEXT', CFBundleExecutable=component,
                OSBundleRequired='Root', OSBundleLibraries={
                    'com.apple.iokit.IOStorageFamily': '2.1', 'com.apple.kpi.iokit': '25.0',
                    'com.apple.kpi.libkern': '25.0', 'com.apple.kpi.mach': '25.0',
                    'com.apple.kpi.private': '25.0'},
                IOKitPersonalities={'NativeVirtioBlock': dict(CFBundleIdentifier=BUNDLE,
                    IOClass='NativeVirtioBlock', IOProviderClass='IOPlatformDevice',
                    IONameMatch='virtio,mmio', IOProbeScore=1000,
                    **{'Protocol Characteristics': dict(PROTOCOL_CHARACTERISTICS)})})
    if transport == 'ufs':
        info['IOKitPersonalities'] = {
            'NativeUfs': dict(CFBundleIdentifier=bundle, IOClass=component,
                              IOProviderClass='IOPlatformDevice', IOProbeScore=1000),
            'NativeUfsRoot': dict(CFBundleIdentifier=bundle, IOClass=component,
                                  IOProviderClass='IOPlatformExpertDevice',
                                  IOMatchCategory='NativeUfsRoot', IOProbeScore=500),
        }
    if display:
        info['IOKitPersonalities']['NativeGOPDisplay'] = dict(
            CFBundleIdentifier=bundle, IOClass='NativeGOPDisplay',
            IOProviderClass='IOPlatformExpertDevice', IOMatchCategory='NativeGOPDisplay',
            IOProbeScore=500)
        info['OSBundleLibraries'].update({
            'com.apple.iokit.IOMobileGraphicsFamily': '1.0.0',
            'com.apple.iokit.IOSurface': '1.0.0', 'com.apple.iokit.IOAVFamily': '1.0.0'})
    (destination / 'Info.plist').write_bytes(plistlib.dumps(info))
    evidence = dict(bundle=bundle, upstream_source_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
                    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                    architecture='arm64e', deployment='macOS 26.5', read_only_transport=transport == 'ufs',
                    explicit_qemu_scratch_writes=transport == 'virtio',
                    hardware_enable_required=transport == 'ufs', root_transport_read_only=True,
                    original_storage_runtime_qualified=False, hardware_admitted=False)
    if display:
        evidence['native_gop_display'] = display
    if transport == 'ufs':
        evidence['macoslog'] = dict(contract=log, default_off=True,
            boot_argument='native-ufs-macoslog', read_only_mode=1, write_mode=2,
            writes_confined_to_preallocated_file=True, filesystem_metadata_writes=False,
            source_sha256={name: hashlib.sha256((root / 'platform/sheng/macos26/storage' / name).read_bytes()).hexdigest()
                           for name in ('macoslog_layout.h', 'macoslog_worker.h')})
        evidence.update(root_partition='macosroot', root_lun=0,
                        android_userdata_used=False, root_media_layout_qualified=False,
                        recovery_root=recovery_root,
                        recovery_disk_image_protocol=dict(PROTOCOL_CHARACTERISTICS),
                        recovery_root_header_sha256=hashlib.sha256((root / 'platform/sheng/macos26/storage/recovery_root.h').read_bytes()).hexdigest(),
                        root_publication_sha256=hashlib.sha256((upstream.parent / 'RootPublication.h').read_bytes()).hexdigest(),
                        recovery_transport_is_not_authentication=True)
        if 'isc' in recovery_root:
            evidence['isc_volatile_overlay'] = dict(seed_read_only=True, disk_writes=False,
                limit_bytes=64 << 20, boot_argument='native-ufs-isc-overlay=1', persistent=False,
                production_header_sha256=hashlib.sha256((upstream.parent / 'RootWindowOverlay.h').read_bytes()).hexdigest(),
                sparse_disk_header_sha256=hashlib.sha256((upstream.parent.parent / 'NativeRamBlock/SparseDisk.h').read_bytes()).hexdigest())
    (destination / 'build.json').write_text(json.dumps(evidence, indent=2) + '\n')
    record['storage_driver' if transport == 'virtio' else 'ufs_driver'] = evidence
