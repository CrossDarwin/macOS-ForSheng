#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile the pinned macOS 26 source machine layer in an isolated SHENG tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/macos26-xnu'
ARCH = 'arm64'
PATCHES = [
    ROOT / 'platform/sheng/macos26/patches/0001-native-sheng-target.patch',
    ROOT / 'platform/sheng/macos26/patches/0002-non-apple-machine-paths.patch',
    ROOT / 'platform/sheng/macos26/patches/0003-staged-kernel-sdk.patch',
    ROOT / 'platform/sheng/macos26/patches/0004-system-abi-identifiers.patch',
    ROOT / 'platform/sheng/macos26/patches/0005-native-cache-and-unused-diagnostics.patch',
    ROOT / 'platform/sheng/macos26/patches/0006-upstream-write-only-diagnostics.patch',
    ROOT / 'platform/sheng/macos26/patches/0007-native-macos-page-layout.patch',
    ROOT / 'platform/sheng/macos26/patches/0008-native-source-selection.patch',
    ROOT / 'platform/sheng/macos26/patches/0009-normal-kernel-archive.patch',
    ROOT / 'platform/sheng/macos26/patches/0010-native-kernel-link.patch',
    ROOT / 'platform/sheng/macos26/patches/0011-native-platform-personalities.patch',
    ROOT / 'platform/sheng/macos26/patches/0012-native-platform-services.patch',
    ROOT / 'platform/sheng/macos26/patches/0013-native-retained-log.patch',
    ROOT / 'platform/sheng/macos26/patches/0014-native-link-map.patch',
    ROOT / 'platform/sheng/macos26/patches/0015-native-physmap-padding.patch',
    ROOT / 'platform/sheng/macos26/patches/0016-native-first-exception-log.patch',
    ROOT / 'platform/sheng/macos26/patches/0017-native-corecrypto-bootstrap.patch',
    ROOT / 'platform/sheng/macos26/patches/0018-native-panic-console-mirror.patch',
    ROOT / 'platform/sheng/macos26/patches/0019-native-console-fallback-mirror.patch',
    ROOT / 'platform/sheng/macos26/patches/0020-native-crypto-module-view.patch',
    ROOT / 'platform/sheng/macos26/patches/0021-native-panic-console-flush.patch',
    ROOT / 'platform/sheng/macos26/patches/0022-native-early-framebuffer-console.patch',
    ROOT / 'UniXNU/patches/xnu/apple-only-cpu-tunables.patch',
    ROOT / 'UniXNU/patches/xnu/native-4k-bootstrap-capacity.patch',
    ROOT / 'UniXNU/patches/xnu/native-dt-panic-region.patch',
    ROOT / 'UniXNU/patches/xnu/local-availability.patch',
    ROOT / 'UniXNU/patches/xnu/cxx-flag-dependencies.patch',
    ROOT / 'platform/sheng/macos26/patches/0023-native-early-exception-screen.patch',
    ROOT / 'platform/sheng/macos26/patches/0024-native-bootstrap-sync-screen.patch',
    ROOT / 'platform/sheng/macos26/patches/0025-native-mmu-transition-vectors.patch',
    ROOT / 'platform/sheng/macos26/patches/0026-native-skip-early-debug-unlock.patch',
    ROOT / 'platform/sheng/macos26/patches/0027-native-bootstrap-stage-strip.patch',
    ROOT / 'platform/sheng/macos26/patches/0028-native-post-mmu-stage-strip.patch',
    ROOT / 'platform/sheng/macos26/patches/0029-native-c-bootstrap-stage-strip.patch',
    ROOT / 'platform/sheng/macos26/patches/0030-native-vm-console-stage-strip.patch',
    ROOT / 'platform/sheng/macos26/patches/0031-native-retained-log-panel.patch',
    ROOT / 'platform/sheng/macos26/patches/0032-native-panel-bounded-conversions.patch',
    ROOT / 'platform/sheng/macos26/patches/0033-native-mapped-status-line.patch',
    ROOT / 'platform/sheng/macos26/patches/0034-native-status-panel-layout.patch',
    ROOT / 'platform/sheng/macos26/patches/0035-native-preconsole-live-log.patch',
    ROOT / 'platform/sheng/macos26/patches/0036-native-live-log-rebind.patch',
    ROOT / 'platform/sheng/macos26/patches/0037-native-panic-io-zero.patch',
    ROOT / 'platform/sheng/macos26/patches/0038-native-security-prelink.patch',
    ROOT / 'platform/sheng/macos26/patches/0039-native-security-init-build.patch',
    ROOT / 'platform/sheng/macos26/patches/0040-native-prelink-structor-signing.patch',
    ROOT / 'platform/sheng/macos26/patches/0041-native-prelink-index-bounds.patch',
    ROOT / 'platform/sheng/macos26/patches/0042-native-security-entry-pac.patch',
    ROOT / 'platform/sheng/macos26/patches/0043-native-corecrypto-single-init.patch',
    ROOT / 'platform/sheng/macos26/patches/0044-native-platform-compatible-match.patch',
    ROOT / 'platform/sheng/macos26/patches/0045-native-fatal-exception-panel.patch',
    ROOT / 'platform/sheng/macos26/patches/0046-native-platform-personality-config.patch',
    ROOT / 'platform/sheng/macos26/patches/0047-native-storage-vm-mappings.patch',
    ROOT / 'platform/sheng/macos26/patches/0048-qemu-development-dyld-ignition.patch',
    ROOT / 'platform/sheng/macos26/patches/0049-native-boot-prelink-identity.patch',
    ROOT / 'platform/sheng/macos26/patches/0050-native-platform-uuid.patch',
    ROOT / 'platform/sheng/macos26/patches/0051-native-multiline-panic-panel.patch',
    ROOT / 'platform/sheng/macos26/patches/0052-native-independent-panic-surface.patch',
    ROOT / 'platform/sheng/macos26/patches/0053-development-dyld-commpage.patch',
]
MACHINE_PATCH = ROOT / 'platform/sheng/macos26/patches/machine-driver-declarations.patch'
CPU_PATCH = ROOT / 'platform/sheng/macos26/patches/machine-cpu-registration.patch'
CPU_INTERRUPT_PATCH = ROOT / 'platform/sheng/macos26/patches/machine-cpu-interrupt-order.patch'


# Preserve diagnostics for exported Apple source/tool-generated code on Clang 27.
# Machine-layer translation units restore these categories to errors below.
UPSTREAM_WARNINGS = (
    'unused-but-set-variable', 'gnu-folding-constant', 'implicit-int-float-conversion',
    'pointer-to-int-cast', 'void-pointer-to-int-cast', 'void-pointer-to-enum-cast',
)


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(*command: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def stage_file(source: Path, destination: Path) -> None:
    """Keep cached dependency timestamps when the staged content is unchanged."""
    source, destination = Path(source), Path(destination)
    if not destination.is_file() or source.read_bytes() != destination.read_bytes():
        shutil.copy2(source, destination)


def save(record: dict) -> None:
    (OUT / 'build.json').write_text(json.dumps(record, indent=2) + '\n')


def run(command: list, name: str, record: dict, cwd: Path = ROOT, env=None) -> None:
    command = [str(item) for item in command]
    log = OUT / 'logs' / (name + '.log')
    print(f'Running - {name}', flush=True)
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    record.setdefault('commands', []).append(dict(command=command, cwd=str(cwd),
                                                 log=str(log.relative_to(OUT)), returncode=result.returncode))
    save(record)
    if result.returncode:
        lines = log.read_text(errors='replace').splitlines()
        first = next((index for index, line in enumerate(lines)
                      if 'error:' in line or 'Undefined symbols' in line or 'fatal error' in line), None)
        if first is not None:
            print('\n'.join(lines[max(0, first - 3):first + 18]), file=sys.stderr)
        print('\n'.join(lines)[-5000:], file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, command)


def refresh_comment_only_patches(source: Path, applied: dict) -> None:
    """Refresh recorded patch comments while retaining unchanged source timestamps."""
    changed = [p for p in PATCHES if str(p.relative_to(ROOT)) in applied
               and sha(p) != applied[str(p.relative_to(ROOT))]]
    if not changed:
        return
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*.*?\*/|//[^\n]*', re.S)

    def code(text):
        return tokens.sub(lambda m: ''.join('\n' for c in m[0] if c == '\n')
                          if m[0].startswith(('/*', '//')) else m[0], text)

    with tempfile.TemporaryDirectory(prefix='comment-refresh-', dir=OUT) as temporary:
        clean = Path(temporary) / 'source'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-hardlinks',
                        ROOT / 'sources/macos26/xnu', clean], check=True)
        for patch in PATCHES:
            if str(patch.relative_to(ROOT)) in applied:
                subprocess.run(['git', '-C', clean, 'apply', patch], check=True)
        paths = subprocess.check_output(['git', '-C', clean, 'ls-files', '--modified',
                                         '--others', '--exclude-standard', '-z']).decode().split('\0')
        updates = []
        for name in filter(None, paths):
            actual, desired = source / name, clean / name
            if (not actual.is_file() or not desired.is_file()
                    or code(actual.read_text()) != code(desired.read_text())):
                raise ValueError('previously applied patch changed beyond comments: ' + name)
            if actual.read_bytes() != desired.read_bytes():
                updates.append((desired, actual))
        for desired, actual in updates:
            stage_file(desired, actual)
    applied.update({str(p.relative_to(ROOT)): sha(p) for p in changed})


def prepare() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'logs').mkdir(exist_ok=True)
    lock = json.loads((ROOT / 'sources.lock.json').read_text())['sources']
    upstream = next(entry for entry in lock if entry['path'] == 'UniXNU')
    if capture('git', '-C', str(ROOT / 'UniXNU'), 'rev-parse', 'HEAD') != upstream['commit']:
        raise ValueError('the hardware implementation must come from the pinned UniXNU revision')
    sources = json.loads((ROOT / 'config/macos26-sources.json').read_text())['sources']
    identities = {}
    for source in sources:
        directory = ROOT / source['path']
        actual = capture('git', '-C', str(directory), 'rev-parse', 'HEAD')
        if actual != source['commit'] or capture('git', '-C', str(directory), 'status', '--porcelain'):
            raise ValueError(f'{source["path"]}: requires the clean pinned macOS 26 source')
        identities[source['path']] = actual
    baseline = json.loads((ROOT / 'config/sheng-baseline.json').read_text())
    if (sha(ROOT / 'config/sheng_defconfig') != baseline['defconfig_sha256']
            or (ROOT / 'config/sheng_defconfig').read_bytes()
            != (ROOT / 'UniXNU-sheng/configs/sheng_defconfig').read_bytes()):
        raise ValueError('the verified full upstream sheng configuration has changed')
    source = OUT / 'source'
    if not source.exists():
        subprocess.run(['git', 'clone', '--shared', '--no-hardlinks',
                        ROOT / 'sources/macos26/xnu', source], check=True)
    if capture('git', '-C', str(source), 'rev-parse', 'HEAD') != identities['sources/macos26/xnu']:
        raise ValueError('refuse to reset a different existing source worktree')
    previous = OUT / 'build.json'
    applied = {}
    if previous.exists():
        previous_record = json.loads(previous.read_text())
        current_diff = subprocess.check_output(['git', '-C', source, 'diff', 'HEAD', '--binary'])
        if hashlib.sha256(current_diff).hexdigest() != previous_record['source_diff_sha256']:
            raise ValueError('isolated source has unrecorded changes; preserve it for inspection')
        applied = previous_record['patches']
        refresh_comment_only_patches(source, applied)
    for patch in PATCHES:
        identity = str(patch.relative_to(ROOT))
        if identity in applied:
            if sha(patch) != applied[identity]:
                raise ValueError(f'previously applied patch changed: {identity}')
            continue
        reverse = subprocess.run(['git', '-C', source, 'apply', '--reverse', '--check', patch],
                                 capture_output=True)
        if reverse.returncode:
            subprocess.run(['git', '-C', source, 'apply', '--check', patch], check=True)
            subprocess.run(['git', '-C', source, 'apply', patch], check=True)
    io_zero = ROOT / 'platform/sheng/macos26/log/io_zero.h'
    stage_file(io_zero, source / 'pexpert/arm/pe_sheng_io_zero.h')
    retained_log = ROOT / 'platform/sheng/macos26/log/retained_log.h'
    stage_file(retained_log, source / 'pexpert/arm/pe_sheng_log.h')
    panel_console = ROOT / 'platform/sheng/macos26/log/panel_console.h'
    stage_file(panel_console, source / 'pexpert/arm/pe_sheng_panel.h')
    panel_font = source / 'osfmk/console/iso_font.c'
    stage_file(panel_font, source / 'pexpert/arm/pe_sheng_font.h')
    early_exception = ROOT / 'platform/sheng/macos26/log/early_exception.h'
    stage_file(early_exception, source / 'osfmk/arm64/sheng_early_exception.h')
    bootstrap_sync = ROOT / 'platform/sheng/macos26/log/bootstrap_sync.h'
    stage_file(bootstrap_sync, source / 'osfmk/arm64/sheng_bootstrap_sync.h')
    bootstrap_trace = ROOT / 'platform/sheng/macos26/log/bootstrap_trace.h'
    stage_file(bootstrap_trace, source / 'osfmk/arm64/sheng_bootstrap_trace.h')
    c_trace = ROOT / 'platform/sheng/macos26/log/c_trace.h'
    stage_file(c_trace, source / 'osfmk/arm64/sheng_c_trace.h')
    vm_trace = ROOT / 'platform/sheng/macos26/log/vm_trace.h'
    stage_file(vm_trace, source / 'osfmk/arm64/sheng_vm_trace.h')
    crypto_image = ROOT / 'platform/sheng/macos26/crypto/native_image.h'
    stage_file(crypto_image, source / 'osfmk/prng/sheng_crypto_image.h')
    subprocess.run(['git', '-C', source, 'add', '-N', 'osfmk/prng/sheng_crypto_image.h', 'pexpert/pexpert/arm64/SHENG.h',
                    'pexpert/arm/pe_sheng_log.h', 'osfmk/arm64/sheng_early_exception.h',
                    'osfmk/arm64/sheng_bootstrap_sync.h', 'osfmk/arm64/sheng_bootstrap_trace.h',
                    'osfmk/arm64/sheng_c_trace.h', 'osfmk/arm64/sheng_vm_trace.h',
                    'pexpert/arm/pe_sheng_panel.h', 'pexpert/arm/pe_sheng_font.h',
                    'pexpert/arm/pe_sheng_io_zero.h'], check=True)
    record = dict(xnu='12377.121.6', darwin='25.5.0', build='25F71', machine='SHENG',
                  deployment='macOS 26.5', sources=identities,
                  architecture=ARCH, native_el1_pac=ARCH == 'arm64e',
                  el0_pac_lifecycle_qualified=False,
                  pac_key_origin='unchanged EL1 firmware handoff banks' if ARCH == 'arm64e' else None,
                  hardware_source_commit=upstream['commit'],
                  patches={str(p.relative_to(ROOT)): sha(p) for p in PATCHES},
                  io_zero_source_sha256=sha(io_zero),
                  retained_log_source_sha256=sha(retained_log),
                  panel_console_source_sha256=sha(panel_console),
                  panel_font_source_sha256=sha(panel_font),
                  early_exception_source_sha256=sha(early_exception),
                  bootstrap_sync_source_sha256=sha(bootstrap_sync),
                  bootstrap_trace_source_sha256=sha(bootstrap_trace),
                  bootstrap_post_mmu_stages=True,
                  bootstrap_c_trace_source_sha256=sha(c_trace),
                  bootstrap_vm_trace_source_sha256=sha(vm_trace),
                  crypto_image_source_sha256=sha(crypto_image),
                  upstream_sheng_defconfig_sha256=baseline['defconfig_sha256'],
                  upstream_sheng_archives=baseline['archives'],
                  purpose='Native machine-layer source compilation; not a bootable kernel',
                  source_archive_built=False, platform_objects_built=False, runnable_kernel=False,
                  stage='source-compilation', full_upstream_sheng_config=False,
                  kernel_page_bytes=16384, virtual_address_bits=47,
                  upstream_warning_only_categories=list(UPSTREAM_WARNINGS),
                  upstream_binary_archives_reused=False, boot_image_generated=False,
                  original_component_abi_qualified=False, hardware_executed=False,
                  source_diff_sha256=hashlib.sha256(subprocess.check_output(
                      ['git', '-C', source, 'diff', 'HEAD', '--binary'])).hexdigest())
    save(record)
    return record


def audit_object(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 32:
        raise ValueError(f'{path.name}: truncated Mach-O object')
    magic, cpu, subtype, kind = struct.unpack_from('<4I', data)
    if (magic, cpu, subtype & 0xff, kind) != (0xfeedfacf, 0x100000c, 2 if ARCH == 'arm64e' else 0, 1):
        raise ValueError(f'{path.name}: expected a real {ARCH} Mach-O object')
    cursor = 32
    deployment = None
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        if cursor + 8 > len(data):
            raise ValueError('truncated Mach-O object command')
        command, length = struct.unpack_from('<II', data, cursor)
        if length < 8 or cursor + length > len(data):
            raise ValueError('invalid Mach-O object command')
        if command == 0x32:
            if length < 24:
                raise ValueError('truncated deployment command')
            deployment = struct.unpack_from('<II', data, cursor + 8)
        cursor += length
    if deployment != (1, 0x1a0500):
        raise ValueError(f'{path.name}: deployment differs from macOS 26.5: {deployment}')
    return dict(sha256=sha(path), bytes=len(data), deployment='macOS 26.5', architecture=ARCH)


def compile_sources(args, record: dict) -> None:
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('compile on the ARM64 macOS runner; Linux supports --prepare-only')
    record['toolchain'] = {name: capture(*command) for name, command in {
        'xcode': ('xcodebuild', '-version'), 'clang': ('xcrun', 'clang', '--version'),
        'sdk': ('xcrun', '--sdk', 'macosx', '--show-sdk-version'),
    }.items()}
    if not record['toolchain']['xcode'].startswith('Xcode 27') or record['toolchain']['sdk'] != '27.0':
        raise ValueError('requires the recorded Xcode 27 / SDK 27.0 build tools')
    kdk_report = json.loads((ROOT / 'out/kdk-verification.json').read_text())
    config = json.loads((ROOT / 'config/macos26.json').read_text())
    if kdk_report['build'] != config['build'] or not kdk_report['trusted_apple_package']:
        raise ValueError('requires the signed, paired macOS 26 KDK')
    for board, spec in config['kernels'].items():
        identity = kdk_report['kernels'][board]
        if identity['kernel_uuid'] != spec['uuid'] or not identity['paired_dwarf_uuid_verified']:
            raise ValueError(f'{board}: unpaired KDK identity')
    expected_kernel = args.kdk_root / 'System/Library/Kernels/kernel.release.t8103'
    if config['kernels']['j313ap']['uuid'] not in capture('xcrun', 'dwarfdump', '--uuid', str(expected_kernel)):
        raise ValueError('selected KDK directory differs from the verified report')
    expanded = args.kdk_root.resolve().parent.parent
    sdk_payload = expanded / 'KDK_SDK.pkg/Payload'
    sdk_headers = kdk_report.get('sdk_headers', {})
    required = 'System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform/CoreEntitlements/V2/API.h'
    if required not in sdk_headers:
        raise ValueError('verified KDK SDK payload lacks the required CoreEntitlements V2 header')
    for relative, digest in sdk_headers.items():
        path = sdk_payload / relative
        if not path.resolve().is_relative_to(sdk_payload.resolve()) or sha(path) != digest:
            raise ValueError(f'verified KDK SDK header changed: {relative}')
    record['kdk_verification_sha256'] = sha(ROOT / 'out/kdk-verification.json')
    record['kdk_sdk_headers'] = sdk_headers
    save(record)
    env = dict(os.environ)
    source = OUT / 'source'
    sdk = OUT / 'kernel-sdk'
    sdk.mkdir(exist_ok=True)
    for relative in sdk_headers:
        destination = sdk / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage_file(sdk_payload / relative, destination)
    env['XNU_AVAILABILITY_PL'] = str(sdk / 'usr/local/libexec/availability.pl')
    run(['make', '-C', ROOT / 'sources/macos26/AvailabilityVersions', 'install',
         f'DSTROOT={sdk}', f'OBJROOT={OUT / "availability"}', f'SYMROOT={OUT / "availability"}',
         f'CMAKE={shutil.which("cmake")}', f'NINJA={shutil.which("ninja")}'], 'availability', record, env=env)
    for relative in ('include', 'private'):
        shutil.copytree(ROOT / 'sources/macos26/libplatform' / relative,
                        sdk / 'usr/local/include', dirs_exist_ok=True, copy_function=stage_file)
    shutil.copytree(ROOT / 'sources/macos26/libplatform/private/platform',
                    sdk / 'System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform',
                    dirs_exist_ok=True, copy_function=stage_file)
    dispatch = sdk / 'usr/local/include/os'
    dispatch.mkdir(parents=True, exist_ok=True)
    for header in sorted((ROOT / 'sources/macos26/libdispatch/os').glob('*.h')):
        result = subprocess.run(['unifdef', '-DKERNEL=1', '-DOS_FIREHOSE_SPI=1',
                                 '-DOS_VOUCHER_ACTIVITY_SPI_TYPES=1',
                                 '-UOS_VOUCHER_ACTIVITY_SPI', str(header)], capture_output=True)
        if result.returncode not in (0, 1):
            raise ValueError(result.stderr.decode(errors='replace'))
        destination = dispatch / header.name
        if not destination.is_file() or destination.read_bytes() != result.stdout:
            destination.write_bytes(result.stdout)
    record['staged_dependency_headers'] = {
        str(path.relative_to(sdk)): sha(path)
        for path in sorted(sdk.rglob('*.h')) if path.is_file()}
    save(record)
    common = ['make', '-C', source, 'SDKROOT=macosx', f'KDKROOT={args.kdk_root}',
              'TARGET_CONFIGS=DEVELOPMENT ARM64 SHENG', f'ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG={ARCH}',
              'ARM64_LARGE_MEMORY=1', 'ARM64_LINK_ADDR=0xfffffe0007004000',
              'RC_DARWIN_KERNEL_VERSION=25.5.0', 'RC_ProjectSourceVersion=12377.121.6',
              'DEPLOYMENT_TARGET_FLAGS=-mmacosx-version-min=26.5 -DXNU_TARGET_OS_OSX',
              'BUILD_LTO=0', 'BOUND_CHECKS=0', 'BUILD_WERROR=1', f'MAKEJOBS=-j{args.jobs}',
              f'KERNEL_SDKROOT={sdk}',
              f'OBJROOT={OUT / "obj"}', f'SYMROOT={OUT / "sym"}', f'DSTROOT={sdk}']
    run(common + ['installhdrs'], 'install-headers', record, env=env)
    # Archive the ordinary kernel translation units without substituting an
    # Apple SoC support library or producing an executable with unresolved ABI.
    failures = []
    try:
        run(common + ['-k', 'build', 'BUILD_STATIC_LINK=1', 'BUILD_XNU_LIBRARY=1',
                      'CFLAGS_KERNEL=-mkernel', 'CXXFLAGS_KERNEL=-fapple-kext',
                      'CFLAGS_EXTRA=-DXNU_NATIVE_ARCH_TIMER=1 -DXNU_DT_PANIC_REGION=1 ' +
                      ' '.join('-Wno-error=' + warning for warning in UPSTREAM_WARNINGS)],
            'source-archive', record, env=env)
    except subprocess.CalledProcessError:
        failures.append('source-archive: compilation failed; see logs/source-archive.log')
    else:
        archive = OUT / 'obj/DEVELOPMENT_ARM64_SHENG/libkernel.development.sheng.a'
        if not archive.is_file() or archive.stat().st_size < 1 << 20:
            failures.append('source-archive: no real kernel archive was produced')
        else:
            record.update(source_archive_built=True, source_archive_sha256=sha(archive),
                          source_archive_bytes=archive.stat().st_size)
        save(record)
    recipe = OUT / 'obj/DEVELOPMENT_ARM64_SHENG/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    if not recipe.is_file():
        record['build_failures'] = failures + ['no IOPlatformExpert compilation record was produced']
        save(record)
        raise ValueError('; '.join(record['build_failures']))
    compile_record = json.loads(recipe.read_text().strip().rstrip(','))
    machine = OUT / 'machine'
    for component in ('ArmDTPlatform', 'ArmCpu'):
        destination = machine / component / (component + '.cpp')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'UniXNU/drivers' / component / destination.name, destination)
    subprocess.run(['git', 'apply', '--directory=' + str(machine.relative_to(ROOT)),
                    str(MACHINE_PATCH)], cwd=ROOT, check=True)
    record['machine_patch_sha256'] = sha(MACHINE_PATCH)
    subprocess.run(['git', 'apply', '--directory=' + str(machine.relative_to(ROOT)),
                    str(CPU_PATCH)], cwd=ROOT, check=True)
    record['cpu_registration_patch_sha256'] = sha(CPU_PATCH)
    subprocess.run(['git', 'apply', '--directory=' + str(machine.relative_to(ROOT)),
                    str(CPU_INTERRUPT_PATCH)], cwd=ROOT, check=True)
    record['cpu_interrupt_order_patch_sha256'] = sha(CPU_INTERRUPT_PATCH)
    record['platform_objects'] = {}
    for component in ('ArmDTPlatform', 'ArmCpu'):
        original = ROOT / f'UniXNU/drivers/{component}/{component}.cpp'
        adapted = machine / component / (component + '.cpp')
        destination = OUT / (component + '.o')
        command, index = [], 0
        arguments = compile_record['arguments']
        while index < len(arguments):
            arg = arguments[index]
            if arg == compile_record['file']:
                command.append(str(adapted))
            elif arg in ('-o', '-MF', '-MT', '-MQ', '-MJ'):
                if arg == '-o':
                    command += ['-o', str(destination)]
                index += 1
            elif arg not in ('-MMD', '-MD', '-MP'):
                command.append(arg)
            index += 1
        command += ['-I', str(source / 'osfmk'), '-Werror', '-Wno-unused-parameter']
        command += ['-Werror=' + warning for warning in UPSTREAM_WARNINGS]
        try:
            run(command, component, record, cwd=Path(compile_record['directory']), env=env)
            record['platform_objects'][component] = dict(source_sha256=sha(original),
                adapted_source_sha256=sha(adapted), **audit_object(destination))
        except (subprocess.CalledProcessError, ValueError) as error:
            failures.append(f'{component}: {error}')
        save(record)
    record['platform_objects_built'] = len(record['platform_objects']) == 2
    record['build_failures'] = failures
    save(record)
    if failures:
        raise ValueError('; '.join(failures))
    if args.link_kernel:
        link_kernel(args, record, common, sdk, source, env)
        if ARCH == 'arm64e':
            from build_macos26_storage import build as build_storage
            build_storage(ROOT, OUT, compile_record, source, run, record, env)
            if args.build_ufs_driver:
                build_storage(ROOT, OUT, compile_record, source, run, record, env,
                              transport='ufs', gop_display=args.build_gop_display)
            save(record)


def link_kernel(args, record, common, sdk, source, env):
    """Use XNU's executable link recipe; missing native contracts remain errors."""
    record.update(stage='executable-link', link_attempted=True, executable_kernel_built=False)
    save(record)
    dispatch = ROOT / 'sources/macos26/libdispatch'
    headers = [dispatch, sdk / 'System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders',
               sdk / 'System/Library/Frameworks/Kernel.framework/Versions/A/Headers',
               sdk / 'usr/local/include', sdk / 'usr/local/include/os',
               sdk / 'usr/local/include/firehose', source / 'EXTERNAL_HEADERS',
               Path(capture('xcrun', '--sdk', 'macosx', '--show-sdk-path')) / 'usr/include']
    run(['xcodebuild', 'install', '-project', dispatch / 'libdispatch.xcodeproj',
         '-target', 'libfirehose_kernel', '-configuration', 'Release', '-sdk', 'macosx',
         '-jobs', str(args.jobs), f'ARCHS={ARCH}', f'VALID_ARCHS={ARCH}', 'ONLY_ACTIVE_ARCH=NO',
         'MACOSX_DEPLOYMENT_TARGET=26.5', 'CODE_SIGNING_ALLOWED=NO',
         'GCC_TREAT_WARNINGS_AS_ERRORS=NO', 'USE_HEADERMAP=NO',
         'HEADER_SEARCH_PATHS=' + ' '.join(str(h) for h in headers),
         f'OBJROOT={OUT / "firehose/obj"}', f'SYMROOT={OUT / "firehose/sym"}',
         f'DSTROOT={sdk}'], 'firehose-kernel', record, env=env)
    firehose = sdk / 'usr/local/lib/kernel/libfirehose_kernel.a'
    alternate = firehose.with_name('liblibfirehose_kernel.a')
    if not firehose.exists() and alternate.exists():
        shutil.copy2(alternate, firehose)
    if not firehose.exists():
        raise ValueError('libdispatch did not install its actual kernel firehose library')
    record['firehose_kernel'] = dict(sha256=sha(firehose), bytes=firehose.stat().st_size)
    # Xcode ships its kernel compiler runtime separately from userspace libSystem.
    resources = Path(capture('xcrun', 'clang', '-print-resource-dir'))
    runtimes = [resources / 'lib/darwin' / name for name in
                ('libclang_rt.cc_kext_osx.a', 'libclang_rt.cc_kext.a')
                if (resources / 'lib/darwin' / name).is_file()]
    if not runtimes:
        raise ValueError('the selected Xcode toolchain has no compiler kernel runtime')
    from build_macos26_crypto import build_provider
    crypto = build_provider(args, record, sdk, source, env)
    crypto_input = '-Wl,-force_load,' + str(crypto) if ARCH == 'arm64e' else str(crypto)
    archives = [crypto_input, str(OUT / 'ArmDTPlatform.o'), str(OUT / 'ArmCpu.o'), str(firehose)]
    native_link_flags = ('-Wl,-headerpad,0x2000 -Wl,-map,'
                         + str(OUT / 'kernel.development.sheng.map'))
    run(common + ['build', 'BUILD_STATIC_LINK=1', 'BUILD_XNU_LIBRARY=0',
                  'CFLAGS_KERNEL=-mkernel', 'CXXFLAGS_KERNEL=-fapple-kext',
                  'CFLAGS_EXTRA=-DXNU_NATIVE_ARCH_TIMER=1 -DXNU_DT_PANIC_REGION=1 ' +
                  ' '.join('-Wno-error=' + w for w in UPSTREAM_WARNINGS),
                  'LD_KERNEL_LIBS=' + str(runtimes[0]),
                  'LD_KERNEL_ARCHIVES=' + ' '.join(archives),
                  'NATIVE_KERNEL_LINK_FLAGS=' + native_link_flags,
                  'DO_CTFMERGE=0'], 'kernel-link', record, env=env)
    binary = OUT / 'obj/DEVELOPMENT_ARM64_SHENG/kernel.development.sheng.unstripped.noctf'
    if not binary.exists() or struct.unpack_from('<I', binary.read_bytes(), 12)[0] != 2:
        raise ValueError('the native linker did not produce an executable Mach-O kernel')
    kernel_bytes = binary.read_bytes()
    for personality in (b"'IOClass'         = ArmDTPlatform;",
                        b"'IOClass'         = ArmCpu;",
                        b"'IONameMatch'     = ( 'device-tree', 'xiaomi,sheng' );"):
        if personality not in kernel_bytes:
            raise ValueError('linked kernel omitted a required SHENG platform personality')
    record['native_platform_personalities_compiled'] = True
    if ARCH == 'arm64e':
        from native_macho import native_chained_fixups
        record['native_pointer_fixups'] = native_chained_fixups(kernel_bytes)
    destination = OUT / 'kernel.development.sheng'
    shutil.copy2(binary, destination)
    from seal_macos26_crypto import seal
    record['corecrypto_integrity'] = seal(destination, ARCH)
    run(['xcrun', 'dsymutil', binary, '-o', OUT / 'kernel.development.sheng.dSYM'],
        'kernel-dsym', record, env=env)
    record.update(executable_kernel_built=True, executable_kernel_sha256=sha(destination),
                  kernel_uuid=capture('xcrun', 'dwarfdump', '--uuid', str(destination)),
                  dsym_uuid=capture('xcrun', 'dwarfdump', '--uuid',
                                   str(OUT / 'kernel.development.sheng.dSYM')),
                  link_map_sha256=sha(OUT / 'kernel.development.sheng.map'),
                  purpose='Native executable link; runtime and userland ABI remain unqualified')
    save(record)


def main() -> None:
    global OUT, ARCH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--link-kernel', action='store_true', help='build runtime and attempt the native executable link')
    parser.add_argument('--build-ufs-driver', action='store_true',
                        help='compile the default-off sheng UFS transport with the paired ARM64E ABI')
    parser.add_argument('--build-gop-display', action='store_true',
                        help='include the default-off paired CPU GOP display in the UFS companion')
    parser.add_argument('--arch', choices=('arm64', 'arm64e'), default='arm64')
    parser.add_argument('--kdk-root', type=Path)
    parser.add_argument('-j', '--jobs', type=int, default=4, choices=range(1, 33))
    args = parser.parse_args()
    if args.build_ufs_driver and (not args.link_kernel or args.arch != 'arm64e'):
        parser.error('--build-ufs-driver requires --link-kernel --arch arm64e')
    if args.build_gop_display and not args.build_ufs_driver:
        parser.error('--build-gop-display requires --build-ufs-driver')
    ARCH = args.arch
    if ARCH == 'arm64e':
        OUT = ROOT / 'out/macos26-xnu-arm64e'
        before = PATCHES.index(ROOT / 'platform/sheng/macos26/patches/0040-native-prelink-structor-signing.patch')
        PATCHES[before:before] = [ROOT / 'platform/sheng/macos26/pac/0001-native-el1-pac-abi.patch',
                                 ROOT / 'platform/sheng/macos26/pac/0002-native-arm64e-chained-startup.patch']
        PATCHES.append(ROOT / 'platform/sheng/macos26/pac/0003-native-user-pac-lifecycle.patch')
        PATCHES.append(ROOT / 'platform/sheng/macos26/pac/0004-native-signing-window-failure.patch')
        PATCHES.append(ROOT / 'platform/sheng/macos26/pac/0005-native-user-a-key-policy.patch')
    # Keep helpers on this configured module when invoked as a script.
    sys.modules['build_macos26_xnu'] = sys.modules[__name__]
    record = prepare()
    if args.prepare_only:
        print(json.dumps(record, indent=2))
        return
    if args.kdk_root is None:
        parser.error('--kdk-root is required for compilation')
    try:
        compile_sources(args, record)
    except Exception as error:
        record['error'] = str(error)
        save(record)
        raise


if __name__ == '__main__':
    main()
