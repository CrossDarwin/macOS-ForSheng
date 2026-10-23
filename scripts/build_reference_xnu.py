#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the pinned UniXNU EL1 reference in a separate tree; never prelink or deploy it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
from unixnu import cli, feeds, kernel, tree
from unixnu.config import Context, parse_config

REFERENCES = {
    'xnu': 'xnu', 'libplatform': 'sources/libplatform',
    'libdispatch': 'sources/libdispatch', 'AvailabilityVersions': 'sources/AvailabilityVersions',
    'libpthread': 'sources/libpthread', 'corecrypto-2023': 'sources/corecrypto-2023',
    'IOStorageFamily': 'sources/IOStorageFamily', 'edk2': 'uefi-sheng/Mu_Basecore',
}


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(jobs: int, upstream_sheng: bool = False) -> tuple:
    for group in ('core', 'feeds'):
        subprocess.run([sys.executable, ROOT / 'scripts/sources.py', 'verify', '--group', group], check=True)
    output = ROOT / ('out/sheng-xnu' if upstream_sheng else 'out/reference-xnu')
    command = ['tree', '-D', str(ROOT / 'UniXNU-sheng'), '--out', str(output / 'work'), '-j', str(jobs)]
    for name, path in REFERENCES.items():
        command += ['--local-module', f'refer:{name}={ROOT / path}']
    ctx = Context(cli.parser().parse_args(command))
    config_path = ROOT / ('config/sheng_defconfig' if upstream_sheng else 'config/reference-xnu_defconfig')
    config = config_path.read_text()
    if upstream_sheng:
        baseline = json.loads((ROOT / 'config/sheng-baseline.json').read_text())
        if (config_path.read_bytes() != (ROOT / 'UniXNU-sheng/configs/sheng_defconfig').read_bytes()
                or sha(config_path) != baseline['defconfig_sha256']
                or sha(ROOT / 'UniXNU-sheng/board.toml') != baseline['board_sha256']):
            raise ValueError('full sheng baseline must match the pinned upstream configuration and board')
    ctx.config = parse_config(config)
    ctx.work.mkdir(parents=True, exist_ok=True)
    ctx.config_path.write_text(config)
    profile = json.loads((ROOT / 'config/reference-xnu.json').read_text())
    if upstream_sheng:
        profile['archives'] = list(ctx.board['kernel']['archives'])
        profile['purpose'] = 'Complete pinned upstream sheng kernel baseline; iPadOS 17 ABI, not macOS userspace'
    else:
        ctx.board['kernel']['archives'] = profile['archives']
    modules = feeds.resolve(ctx)
    definitions, _ = feeds.read_sources(ctx)
    for name in REFERENCES:
        key = ('refer', name)
        modules[key].source = dict(definitions.get(key, {}))
    xnu = modules[('refer', 'xnu')].source
    if xnu.get('version') != profile['xnu'] or xnu.get('darwin') != profile['darwin']:
        raise ValueError('reference profile differs from the pinned UniXNU XNU ABI')
    # The upstream header restorer verifies each Git blob; address its API requests by immutable commits.
    xnu['driverkit_tag'] = profile['omitted_headers']['driverkit']['commit']
    xnu['trustcache_tag'] = profile['omitted_headers']['trustcache']['commit']
    tree.assemble(ctx, modules)
    for entry in profile['archives']:
        if not (ctx.tree / 'scripts' / entry.split()[0]).is_file():
            raise ValueError(f'missing archive builder: {entry}')
    identity = {}
    for relative in ('UniXNU', 'UniXNU-sheng', *REFERENCES.values()):
        path = ROOT / relative
        identity[relative] = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    record = {
        'purpose': profile['purpose'], 'xnu': profile['xnu'], 'darwin': profile['darwin'],
        'profile_sha256': sha(ROOT / 'config/reference-xnu.json'),
        'defconfig_sha256': sha(config_path), 'sources_lock_sha256': sha(ROOT / 'sources.lock.json'),
        'sources': identity, 'omitted_headers': profile['omitted_headers'],
        'patches': {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / 'patches').glob('*/*.patch'))},
        'upstream_kernel_patches': {
            str(p.relative_to(ctx.tree)): sha(p)
            for folder in (ctx.tree / 'patches/xnu', ctx.tree / 'kits/NativePrelink/patches')
            for p in sorted(folder.glob('*.patch'))
        },
        'config': ctx.config, 'archives': profile['archives'], 'jobs': jobs,
        'built': False, 'hardware_executed': False, 'macos27_abi_qualified': False,
        'full_upstream_sheng_config': upstream_sheng,
        'upstream_defconfig_sha256': sha(ROOT / 'UniXNU-sheng/configs/sheng_defconfig'),
        'upstream_board_sha256': sha(ROOT / 'UniXNU-sheng/board.toml'),
        'output_directory': str(output.relative_to(ROOT)),
    }
    if upstream_sheng:
        # These are consumed by upstream builders, not replaceable build stubs.
        required_inputs = {
            'build/storage-abi/interface-audit.json': 'scripts/build-native-virtio-bindings.py',
            'build/native-prelink/native-owner-ufs-rootauth3-candidate.macho': 'scripts/build-sheng-platform-power.py',
            'build/native-prelink/native-owner-ufs-rootauth3-candidate.json': 'scripts/audit-amfi-pmgr-contract.py',
            'build/native-prelink/native-owner-mobile-graphics-candidate.macho': 'scripts/build-native-legacy-display.py',
            'build/native-prelink/native-owner-mobile-graphics-candidate.json': 'scripts/audit-mobile-graphics-legacy.py',
            'build/native-virtio-block-verified-bundle/libNativeVirtioBlock.a': 'XNU_NATIVE_VIRTIO_BLOCK_ARCHIVE',
            'build/verified-root-os-xnu-bundle/libVerifiedRootProbe.a': 'XNU_VERIFIED_ROOT_ARCHIVE',
        }
        later = list((ctx.tree / 'build/native-prelink').glob('native-owner-ufs-cpu-desktop-*-candidate.macho'))
        record['observed_external_inputs'] = {
            name: {'consumer': consumer, 'present': (ctx.tree / name).is_file(),
                   'later_candidate_may_be_accepted_by_upstream': bool(later) if 'candidate.' in name else False}
            for name, consumer in required_inputs.items()
        }
        record['dependency_audit_complete'] = False
    output.mkdir(parents=True, exist_ok=True)
    (output / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    return ctx, modules, record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true', help='validate and assemble without compiling')
    parser.add_argument('--upstream-sheng', action='store_true',
                        help='use every upstream sheng option and archive without overrides')
    parser.add_argument('-j', '--jobs', type=int, default=min(os.cpu_count() or 2, 4))
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error('jobs must be between 1 and 32')
    ctx, modules, record = prepare(args.jobs, args.upstream_sheng)
    if args.prepare_only:
        print(json.dumps(record, indent=2))
        return
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('compile on the pinned ARM64 macOS Actions runner; Linux supports --prepare-only')
    output = ROOT / record['output_directory']
    for name, command in {
        'xcode': ['xcodebuild', '-version'], 'clang': ['xcrun', 'clang', '--version'],
        'iphoneos_sdk': ['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'],
        'macos_sdk': ['xcrun', '--sdk', 'macosx', '--show-sdk-version'],
    }.items():
        record[name] = subprocess.check_output(command, text=True).strip()
    manifest = output / 'build.json'
    manifest.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('xcode', 'macos_sdk', 'iphoneos_sdk', 'clang')}, indent=2), flush=True)
    # This is the older iOS 17 source reference; its SDK need not share macOS's version number.
    xcode_major = record['xcode'].splitlines()[0].removeprefix('Xcode ').split('.')[0]
    if (xcode_major != '27' or record['macos_sdk'] != '27.0'
            or int(record['iphoneos_sdk'].split('.')[0]) < 17):
        raise ValueError(f'unqualified reference toolchain: Xcode={record["xcode"]!r}, '
                         f'macOS SDK={record["macos_sdk"]}, iPhoneOS SDK={record["iphoneos_sdk"]}')
    kernel.build(ctx, modules)
    binary = ctx.tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
    if not binary.is_file():
        raise ValueError('kernel builder did not produce the expected source Mach-O')
    subprocess.run([sys.executable, ctx.tree / 'scripts/audit-xnu-kernel.py', binary], check=True)
    shutil.copy2(ctx.tree / 'build/xnu/kernel-audit.json', output / 'kernel-audit.json')
    source_hash = sha(binary)
    artifact = kernel.prelink(ctx) if args.upstream_sheng else binary
    shutil.copy2(artifact, output / 'kernel.macho')
    record.update(built=True, kernel_sha256=sha(artifact), kernel_bytes=artifact.stat().st_size,
                  source_kernel_sha256=source_hash, prelinked=args.upstream_sheng,
                  kernel_file='kernel.macho')
    restored = ctx.tree / '.cache/sources/xnu-restored-headers.json'
    if restored.is_file():
        shutil.copy2(restored, output / 'restored-headers.json')
        record['restored_headers_sha256'] = sha(restored)
    manifest.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
