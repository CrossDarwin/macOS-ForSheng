#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile the pinned macOS 26 source machine layer in an isolated SHENG tree."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out/macos26-xnu'
PATCHES = [
    ROOT / 'platform/sheng/macos26/patches/0001-native-sheng-target.patch',
    ROOT / 'platform/sheng/macos26/patches/0002-non-apple-machine-paths.patch',
    ROOT / 'platform/sheng/macos26/patches/0003-staged-kernel-sdk.patch',
    ROOT / 'UniXNU/patches/xnu/apple-only-cpu-tunables.patch',
    ROOT / 'UniXNU/patches/xnu/native-4k-bootstrap-capacity.patch',
    ROOT / 'UniXNU/patches/xnu/native-dt-panic-region.patch',
    ROOT / 'UniXNU/patches/xnu/local-availability.patch',
    ROOT / 'UniXNU/patches/xnu/cxx-flag-dependencies.patch',
]


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(*command: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


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
        print(log.read_text(errors='replace')[-10000:], file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, command)


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
    if previous.exists():
        previous_record = json.loads(previous.read_text())
        current_diff = subprocess.check_output(['git', '-C', source, 'diff', 'HEAD', '--binary'])
        if hashlib.sha256(current_diff).hexdigest() != previous_record['source_diff_sha256']:
            raise ValueError('isolated source has unrecorded changes; preserve it for inspection')
    for patch in PATCHES:
        reverse = subprocess.run(['git', '-C', source, 'apply', '--reverse', '--check', patch],
                                 capture_output=True)
        if reverse.returncode:
            subprocess.run(['git', '-C', source, 'apply', '--check', patch], check=True)
            subprocess.run(['git', '-C', source, 'apply', patch], check=True)
    subprocess.run(['git', '-C', source, 'add', '-N', 'pexpert/pexpert/arm64/SHENG.h'], check=True)
    record = dict(xnu='12377.121.6', darwin='25.5.0', build='25F71', machine='SHENG',
                  deployment='macOS 26.5', sources=identities,
                  hardware_source_commit=upstream['commit'],
                  patches={str(p.relative_to(ROOT)): sha(p) for p in PATCHES},
                  upstream_sheng_defconfig_sha256=baseline['defconfig_sha256'],
                  upstream_sheng_archives=baseline['archives'],
                  purpose='Native machine-layer source compilation; not a bootable kernel',
                  source_archive_built=False, platform_objects_built=False, runnable_kernel=False,
                  stage='source-compilation', full_upstream_sheng_config=False,
                  upstream_binary_archives_reused=False, boot_image_generated=False,
                  original_component_abi_qualified=False, hardware_executed=False,
                  source_diff_sha256=hashlib.sha256(subprocess.check_output(
                      ['git', '-C', source, 'diff', 'HEAD', '--binary'])).hexdigest())
    save(record)
    return record


def audit_object(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 32 or struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise ValueError(f'{path.name}: expected a real ARM64 Mach-O object')
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
    return dict(sha256=sha(path), bytes=len(data), deployment='macOS 26.5', architecture='arm64')


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
    record['kdk_verification_sha256'] = sha(ROOT / 'out/kdk-verification.json')
    save(record)
    env = dict(os.environ)
    source = OUT / 'source'
    sdk = OUT / 'kernel-sdk'
    sdk.mkdir(exist_ok=True)
    env['XNU_AVAILABILITY_PL'] = str(sdk / 'usr/local/libexec/availability.pl')
    run(['make', '-C', ROOT / 'sources/macos26/AvailabilityVersions', 'install',
         f'DSTROOT={sdk}', f'OBJROOT={OUT / "availability"}', f'SYMROOT={OUT / "availability"}',
         f'CMAKE={shutil.which("cmake")}', f'NINJA={shutil.which("ninja")}'], 'availability', record, env=env)
    for relative in ('include', 'private'):
        shutil.copytree(ROOT / 'sources/macos26/libplatform' / relative,
                        sdk / 'usr/local/include', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'sources/macos26/libplatform/private/platform',
                    sdk / 'System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform',
                    dirs_exist_ok=True)
    dispatch = sdk / 'usr/local/include/os'
    dispatch.mkdir(parents=True, exist_ok=True)
    for header in sorted((ROOT / 'sources/macos26/libdispatch/os').glob('*.h')):
        result = subprocess.run(['unifdef', '-DKERNEL=1', '-DOS_FIREHOSE_SPI=1',
                                 '-DOS_VOUCHER_ACTIVITY_SPI_TYPES=1',
                                 '-UOS_VOUCHER_ACTIVITY_SPI', str(header)], capture_output=True)
        if result.returncode not in (0, 1):
            raise ValueError(result.stderr.decode(errors='replace'))
        (dispatch / header.name).write_bytes(result.stdout)
    record['staged_dependency_headers'] = {
        str(path.relative_to(sdk)): sha(path)
        for path in sorted(sdk.rglob('*.h')) if path.is_file()}
    save(record)
    common = ['make', '-C', source, 'SDKROOT=macosx', f'KDKROOT={args.kdk_root}',
              'TARGET_CONFIGS=DEVELOPMENT ARM64 SHENG', 'ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG=arm64',
              'ARM64_LARGE_MEMORY=0', 'ARM64_LINK_ADDR=0xfffffff007004000',
              'RC_DARWIN_KERNEL_VERSION=25.5.0', 'RC_ProjectSourceVersion=12377.121.6',
              'DEPLOYMENT_TARGET_FLAGS=-mmacosx-version-min=26.5 -DXNU_TARGET_OS_OSX',
              'BUILD_LTO=0', 'BOUND_CHECKS=0', 'BUILD_WERROR=1', f'MAKEJOBS=-j{args.jobs}',
              f'KERNEL_SDKROOT={sdk}',
              f'OBJROOT={OUT / "obj"}', f'SYMROOT={OUT / "sym"}', f'DSTROOT={sdk}']
    run(common + ['installhdrs'], 'install-headers', record, env=env)
    # Archive the ordinary kernel translation units without substituting an
    # Apple SoC support library or producing an executable with unresolved ABI.
    run(common + ['build', 'BUILD_STATIC_LINK=1', 'BUILD_XNU_LIBRARY=1', 'CFLAGS_KERNEL=-mkernel',
                  'CFLAGS_EXTRA=-DXNU_NATIVE_ARCH_TIMER=1 -DXNU_DT_PANIC_REGION=1'],
        'source-archive', record, env=env)
    archive = OUT / 'obj/DEVELOPMENT_ARM64_SHENG/libkernel.development.sheng.a'
    if not archive.is_file() or archive.stat().st_size < 1 << 20:
        raise ValueError('source compilation did not produce a real kernel archive')
    record.update(source_archive_built=True, source_archive_sha256=sha(archive),
                  source_archive_bytes=archive.stat().st_size)
    save(record)
    recipe = OUT / 'obj/DEVELOPMENT_ARM64_SHENG/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    compile_record = json.loads(recipe.read_text().strip().rstrip(','))
    record['platform_objects'] = {}
    for component in ('ArmDTPlatform', 'ArmCpu'):
        original = ROOT / f'UniXNU/drivers/{component}/{component}.cpp'
        destination = OUT / (component + '.o')
        command, index = [], 0
        arguments = compile_record['arguments']
        while index < len(arguments):
            arg = arguments[index]
            if arg == compile_record['file']:
                command.append(str(original))
            elif arg in ('-o', '-MF', '-MT', '-MQ', '-MJ'):
                if arg == '-o':
                    command += ['-o', str(destination)]
                index += 1
            elif arg not in ('-MMD', '-MD', '-MP'):
                command.append(arg)
            index += 1
        command += ['-I', str(source / 'osfmk'), '-Werror', '-Wno-unused-parameter']
        run(command, component, record, cwd=Path(compile_record['directory']), env=env)
        record['platform_objects'][component] = dict(source_sha256=sha(original), **audit_object(destination))
        save(record)
    record['platform_objects_built'] = True
    save(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--kdk-root', type=Path)
    parser.add_argument('-j', '--jobs', type=int, default=4, choices=range(1, 33))
    args = parser.parse_args()
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
