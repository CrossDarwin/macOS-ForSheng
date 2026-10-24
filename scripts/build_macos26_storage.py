#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build pinned native transports against the paired macOS storage headers."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess

from native_macho import macho

BUNDLE = 'org.unixnu.driver.NativeVirtioBlock'
PROTOCOL_CHARACTERISTICS = {
    'Physical Interconnect': 'Virtual Interface',
    'Physical Interconnect Location': 'External',
}


def build(root, out, compile_record, source, run, record, env, *, transport='virtio'):
    if transport not in ('virtio', 'ufs'):
        raise ValueError('unsupported native storage transport')
    component = 'NativeVirtioBlock' if transport == 'virtio' else 'NativeUfs'
    bundle = BUNDLE if transport == 'virtio' else 'org.blu-sharky.NativeUfs'
    directory = 'storage-driver' if transport == 'virtio' else 'ufs-driver'
    destination = out / directory
    destination.mkdir(exist_ok=True)
    upstream = root / 'UniXNU/drivers' / component / (component + '.cpp')
    include = destination / 'include/IOKit/storage'
    include.mkdir(parents=True, exist_ok=True)
    for header in (root / 'sources/macos26/IOStorageFamily').glob('*.h'):
        (include / header.name).write_bytes(header.read_bytes())
    wrapper = destination / (component + '.cpp')
    entry_prefix = 'sheng_virtio' if transport == 'virtio' else 'sheng_ufs'
    wrapper.write_text(
        '#include <TargetConditionals.h>\n'
        'static_assert(TARGET_OS_OSX == 1, "requires macOS storage ABI");\n'
        f'#include "{upstream}"\n'
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
    (destination / 'Info.plist').write_bytes(plistlib.dumps(info))
    evidence = dict(bundle=bundle, upstream_source_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),
                    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                    architecture='arm64e', deployment='macOS 26.5', read_only_transport=transport == 'ufs',
                    explicit_qemu_scratch_writes=transport == 'virtio',
                    hardware_enable_required=transport == 'ufs', root_transport_read_only=True,
                    original_storage_runtime_qualified=False, hardware_admitted=False)
    if transport == 'ufs':
        evidence.update(root_partition='macosroot', root_lun=0,
                        android_userdata_used=False, root_media_layout_qualified=False)
    (destination / 'build.json').write_text(json.dumps(evidence, indent=2) + '\n')
    record['storage_driver' if transport == 'virtio' else 'ufs_driver'] = evidence
