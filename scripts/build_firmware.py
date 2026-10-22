#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build and audit the pinned sheng UEFI without deploying it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / 'UniXNU-sheng'


def link(path, target):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        if not path.is_symlink() or path.resolve() != target.resolve():
            raise ValueError(f'refusing to replace existing {path}')
        return
    path.symlink_to(target.resolve(), target_is_directory=target.is_dir())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm-bin', type=Path, required=True)
    parser.add_argument('--iasl-bin', type=Path, required=True)
    parser.add_argument('--fetch-firmware', action='store_true', help='download the pinned 7 GiB vendor archive if needed')
    parser.add_argument('--bootimg', action='store_true', help='also package a UEFI-only Android boot container')
    args = parser.parse_args()
    env = dict(os.environ, PATH=f'{args.llvm_bin.resolve()}:{args.iasl_bin.resolve()}:{os.environ["PATH"]}',
               CLANG_BIN=str(args.llvm_bin.resolve()) + '/')
    logs = ROOT / 'out/logs'
    logs.mkdir(parents=True, exist_ok=True)
    def run(command, cwd=ROOT, name='firmware'):
        with (logs / (name+'.log')).open('w') as output:
            subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                           stdout=output, stderr=subprocess.STDOUT, check=True)
    for binary in ('clang', 'llvm-lib', 'lld-link'):
        if not (args.llvm_bin / binary).is_file():
            raise ValueError(f'missing LLVM tool {binary}')
    if not (args.iasl_bin / 'iasl').is_file():
        raise ValueError('missing iasl')
    firmware = DEVICE / '.cache/firmware/sheng'
    manifest = firmware / 'porting-inputs.json'
    if not manifest.exists() or json.loads(manifest.read_text()).get('archive_md5') != '31450b6677d9e46edc4937c3f797c51d':
        if not args.fetch_firmware:
            raise ValueError('verified vendor input missing; pass --fetch-firmware to fetch the pinned archive')
        run(['python3', 'scripts/download-sheng-firmware.py', '--connections', '32'], DEVICE, 'vendor-download')
        run(['python3', 'scripts/extract-sheng-firmware.py'], DEVICE, 'vendor-extract')
    cmake = [shutil.which('cmake')] if shutil.which('cmake') else ['uvx', '--from', 'cmake==3.31.6', 'cmake']
    run([*cmake, '-S', ROOT/'sources/uefitool/UEFIExtract', '-B', ROOT/'out/uefiextract'], name='uefiextract-configure')
    run([*cmake, '--build', ROOT/'out/uefiextract', '-j4'], name='uefiextract-build')
    link(DEVICE/'build/tools/uefiextract/uefiextract', ROOT/'out/uefiextract/uefiextract')
    link(DEVICE/'uefi-sheng', ROOT/'uefi-sheng')
    (firmware/'uefi-binaries').mkdir(exist_ok=True)
    link(ROOT/'uefi-sheng/Binaries/sheng', firmware/'uefi-binaries')
    image = firmware/'porting-inputs/uefi.elf'
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    dump = image.with_name(image.name+'.dump')
    stamp = image.with_name(image.name+'.dump.sha256')
    if dump.exists() and (not stamp.exists() or stamp.read_text().strip() != digest):
        archived = dump.with_name(dump.name+'.previous')
        if archived.exists():
            raise ValueError('preserve or move previous UEFI extraction before changing inputs again')
        dump.rename(archived)
    run(['python3', 'scripts/import-sheng-uefi.py'], DEVICE, 'vendor-import')
    stamp.write_text(digest+'\n')
    run(['python3', 'scripts/fetch-sheng-dts.py'], DEVICE, 'sheng-dts')
    base = ['python3', ROOT/'UniXNU/unixnu']
    options = ['-D', DEVICE, '--local-module', f'refer:edk2={ROOT / "uefi-sheng/Mu_Basecore"}']
    run([*base, 'tree', *options], name='firmware-tree')
    tree = ROOT/'UniXNU/out/sheng/tree'
    link(tree/'uefi-sheng', ROOT/'uefi-sheng')
    link(tree/'.cache/linux-dts', DEVICE/'.cache/linux-dts')
    link(tree/'build/sheng', DEVICE/'build/sheng')
    run([*base, 'build', 'firmware', *options, '--uefi', ROOT/'uefi-sheng',
         '--edk2', ROOT/'uefi-sheng/Mu_Basecore', '-j4'], name='firmware')
    run(['python3', 'scripts/check-sheng-fv.py'], DEVICE, 'firmware-fv')
    fd = ROOT/'uefi-sheng/Build/shengPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd'
    record = dict(file=fd.name, bytes=fd.stat().st_size, sha256=hashlib.sha256(fd.read_bytes()).hexdigest(),
                  deployed=False, hardware_qualified=False)
    record['vendor_archive_sha256'] = json.loads(manifest.read_text())['archive_sha256']
    record['sources_lock_sha256'] = hashlib.sha256((ROOT/'sources.lock.json').read_bytes()).hexdigest()
    if args.bootimg:
        command = ['python3', 'scripts/package-sheng-boot.py']
        if not shutil.which('qemu-system-aarch64', path=env['PATH']):
            command.append('--skip-qemu')
        run(command, DEVICE, 'firmware-bootimg')
        record['bootimg'] = json.loads((DEVICE/'build/sheng/boot/report.json').read_text())
    (ROOT/'out/firmware-build.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
