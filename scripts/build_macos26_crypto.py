#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build Apple's pinned module-26 C provider against the staged native XNU SDK."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess

from build_macos26_xnu import ROOT, OUT, audit_object, capture, run, save, sha


def names(path: Path, mode: str) -> set[str]:
    return {line.strip() for line in capture('xcrun', 'nm', '-g', mode, '-j', str(path)).splitlines()
            if line.startswith('_')}


def build_provider(args, record: dict, sdk: Path, xnu: Path, env: dict) -> Path:
    source = ROOT / 'sources/macos26/corecrypto'
    work = OUT / 'corecrypto'
    work.mkdir(exist_ok=True)
    run(['plutil', '-convert', 'json', '-o', work / 'project.json',
         source / 'corecrypto.xcodeproj/project.pbxproj'], 'corecrypto-project', record)
    objects = json.loads((work / 'project.json').read_text())['objects']
    parents = {child: key for key, value in objects.items() for child in value.get('children', [])}

    def resolve(key):
        entry = objects[key]
        if entry.get('sourceTree') == 'SOURCE_ROOT' or key not in parents:
            return source / entry.get('path', '')
        if entry.get('sourceTree') != '<group>':
            raise ValueError(f'unsupported crypto source reference: {entry}')
        return resolve(parents[key]) / entry.get('path', '')

    target = next(v for v in objects.values()
                  if v.get('isa') == 'PBXNativeTarget' and v.get('name') == 'corecrypto_kext')
    phase = next(objects[key] for key in target['buildPhases']
                 if objects[key]['isa'] == 'PBXSourcesBuildPhase')
    sources = [resolve(objects[key]['fileRef']) for key in phase['files']
               if objects[objects[key]['fileRef']].get('path', '').endswith('.c')]
    if not sources or any(not p.is_file() or not p.resolve().is_relative_to(source) for p in sources):
        raise ValueError('corecrypto kext source phase contains missing or external sources')
    include = work / 'include/corecrypto'
    include.mkdir(parents=True, exist_ok=True)
    for header in source.glob('*/corecrypto/*.h'):
        link = include / header.name
        if link.exists() and link.resolve() != header.resolve():
            raise ValueError(f'conflicting crypto header: {header.name}')
        if not link.exists():
            link.symlink_to(header)
    framework = sdk / 'System/Library/Frameworks/Kernel.framework/Versions/A'
    command = ['xcrun', '--sdk', 'macosx', 'clang', '-target', 'arm64-apple-macos26.5',
               '-isysroot', capture('xcrun', '--sdk', 'macosx', '--show-sdk-path'),
               '-mkernel', '-ffreestanding', '-fno-builtin', '-fno-stack-check',
               '-std=gnu99', '-fblocks', '-O2', '-g', '-fno-vectorize', '-fno-slp-vectorize',
               '-mno-implicit-float', '-DKERNEL=1', '-DKERNEL_PRIVATE=1', '-DBUILDKERNEL=1',
               '-DCC_USE_ASM=0', '-DNDEBUG=1', '-DCC_DISABLE_RSAKEYGEN=1',
               '-Wno-deprecated-declarations', '-Wno-incompatible-library-redeclaration',
               '-I' + str(include.parent), '-I' + str(framework / 'PrivateHeaders'),
               '-I' + str(framework / 'Headers'), '-I' + str(sdk / 'usr/local/include')]
    for folder in sorted({h.parent for h in source.rglob('*.h')
                          if 'test' not in str(h.relative_to(source)).lower()}):
        command += ['-I', str(folder)]
    kernel_archive = OUT / 'obj/DEVELOPMENT_ARM64_SHENG/libkernel.development.sheng.a'
    kernel_names = names(kernel_archive, '-U')
    report = dict(source_revision=record['sources']['sources/macos26/corecrypto'], module='26.0',
                  deployment='macOS 26.5', assembly_enabled=False, default_post_required=True,
                  original_component_abi_qualified=False, runtime_post_passed=False)
    record['corecrypto'] = report

    def compile_variant(variant: str, extra: list[str]) -> Path:
        object_dir = work / variant
        object_dir.mkdir(exist_ok=True)
        full_command = command + extra
        (work / (variant + '-command.json')).write_text(json.dumps(full_command, indent=2) + '\n')

        def compile_one(path):
            relative = str(path.relative_to(source))
            name = hashlib.sha256(relative.encode()).hexdigest()[:12] + '-' + path.stem
            destination = object_dir / (name + '.o')
            identity = hashlib.sha256((sha(path) + json.dumps(full_command)).encode()).hexdigest()
            stamp = destination.with_suffix('.identity')
            if destination.exists() and stamp.exists() and stamp.read_text() == identity:
                return destination, 0, ''
            result = subprocess.run([*full_command, '-c', str(path), '-o', str(destination)],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            (OUT / 'logs' / ('corecrypto-' + variant + '-' + name + '.log')).write_text(result.stdout)
            if result.returncode == 0:
                audit_object(destination)
                stamp.write_text(identity)
            return destination, result.returncode, result.stdout

        print(f'Running - corecrypto {variant} ({len(sources)} C files)', flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
            results = list(executor.map(compile_one, sources))
        failures = [(str(p), code, diagnostic[-2500:]) for p, code, diagnostic in results if code]
        report[variant] = dict(sources=len(sources), failures=failures)
        save(record)
        if failures:
            raise ValueError(f'corecrypto {variant} compile failed: {failures[:3]}')
        archive = work / ('libcorecrypto-' + variant + '.a')
        archive.unlink(missing_ok=True)
        run(['xcrun', 'ar', 'rcs', archive, *[p for p, _, _ in results]],
            'corecrypto-' + variant + '-archive', record)
        return archive

    plain = compile_variant('plain', [])
    collisions = sorted(names(plain, '-U') & kernel_names)
    if any(not name[1:].isidentifier() for name in collisions):
        raise ValueError('crypto namespace collision is not representable in C')
    namespace = work / 'namespace.h'
    namespace.write_text(''.join(f'#define {name[1:]} sheng_cc26_{name[1:]}\n' for name in collisions))
    archive = compile_variant('native', ['-include', str(namespace)])
    defined = names(archive, '-U')
    missing = sorted(names(archive, '-u') - defined - kernel_names)
    duplicate = sorted(defined & kernel_names)
    report.update(archive_sha256=sha(archive), namespaced_globals=collisions,
                  missing_kernel_symbols=missing, duplicate_kernel_symbols=duplicate,
                  # The public provider predates the sized digest/HMAC tail of this XNU table.
                  sized_digest_hmac_callbacks_implemented=False)
    save(record)
    if missing or duplicate:
        raise ValueError(f'corecrypto external link contract: missing={missing}, duplicate={duplicate}')
    return archive
