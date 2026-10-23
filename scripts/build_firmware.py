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
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / 'UniXNU-sheng'
PROBE_GUID = '624b1b42-3618-4a59-b6b3-d5843a49cd21'
APPLICATION_GUID = '9b665204-a133-47a2-9396-9e2b370a4e25'
NATIVE_GUID = '4e240ccd-9e9a-4bf1-832d-4237392fc59f'
REGISTRAR_GUID = '29b950cf-586d-49ea-9d71-f88645ccdaf6'


def audit_entry(fd, probe_only, native_el1=False):
    """Check extracted FV contents and the registrar's compiled PCD before packaging."""
    files = {}
    for info in fd.with_name(fd.name+'.dump').rglob('info.txt'):
        fields = {}
        for line in info.read_text().splitlines():
            if ': ' in line:
                key, value = line.split(': ', 1)
                fields.setdefault(key, value)
        if fields.get('Type') == 'File':
            files[fields.get('File GUID', '').lower()] = info.parent
    if (PROBE_GUID in files) != probe_only:
        raise ValueError('firmware probe inclusion differs from the requested build mode')
    if (NATIVE_GUID in files) != native_el1:
        raise ValueError('native EL1 probe inclusion differs from the requested build mode')
    registrar = files.get(REGISTRAR_GUID)
    if registrar is None:
        raise ValueError('missing UniXNU FV boot registrar')
    code = []
    for info in registrar.rglob('info.txt'):
        if 'Subtype: PE32 image' in info.read_text():
            code.append(info.with_name('body.bin').read_bytes())
    expected = NATIVE_GUID if native_el1 else PROBE_GUID if probe_only else APPLICATION_GUID
    if len(code) != 1 or uuid.UUID(expected).bytes_le not in code[0]:
        raise ValueError('compiled FV registrar does not select the requested application')
    return dict(application_guid=expected, embedded_probe=probe_only or native_el1,
                registrar_pcd_checked=True, hardware_executed=False)


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
    parser.add_argument('--boot-header', type=int, choices=(0, 4), default=4,
                        help='Android container version; default matches the stock v4 header')
    parser.add_argument('--preflight-only', action='store_true',
                        help='embed ShengPreflight and select its FV entry; no guest or storage volume needed')
    parser.add_argument('--native-el1', action='store_true', help='embed the native EL1 granule/PAC probe in FV')
    parser.add_argument('--compression', choices=('gzip', 'none'), default='gzip', help='v4 kernel payload encoding')
    parser.add_argument('--boot-template', type=Path, help='copy v4 loader metadata from the backed-up boot image of the current slot')
    args = parser.parse_args()
    if args.preflight_only and args.native_el1:
        parser.error('select one standalone application')
    if args.boot_header == 0 and args.compression != 'gzip':
        parser.error('uncompressed payload currently requires the v4 container')
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
    if args.preflight_only:
        link(ROOT/'uefi-sheng/ShengPreflight', DEVICE/'drivers/ShengPreflight')
    if args.native_el1:
        link(ROOT/'uefi-sheng/ShengNativeEl1', ROOT/'probes/el1-native')
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
    command = [*base, 'build', 'firmware', *options, '--uefi', ROOT/'uefi-sheng',
               '--edk2', ROOT/'uefi-sheng/Mu_Basecore', '-j4']
    if args.preflight_only:
        command.extend(['--firmware-define', 'SHENG_PREFLIGHT_ONLY=1'])
    if args.native_el1:
        command.extend(['--firmware-define', 'SHENG_NATIVE_EL1_PROBE=1'])
    run(command, name='firmware')
    run(['python3', 'scripts/check-sheng-fv.py'], DEVICE, 'firmware-fv')
    fd = ROOT/'uefi-sheng/Build/shengPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd'
    record = dict(file=fd.name, bytes=fd.stat().st_size, sha256=hashlib.sha256(fd.read_bytes()).hexdigest(),
                  deployed=False, hardware_qualified=False)
    record['preflight_only'] = args.preflight_only or args.native_el1
    record['native_el1'] = args.native_el1
    if args.native_el1:
        record['native_el1_sources_sha256'] = {
            name: hashlib.sha256((ROOT/'probes/el1-native'/name).read_bytes()).hexdigest()
            for name in ('NativeEl1.c', 'NativeEl1.h', 'NativeEl1.inf', 'native.S',
                         'Native47.c', 'layout47.h', 'layout47.S')}
    record['patches_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT/'patches').glob('*/*.patch'))}
    record['vendor_archive_sha256'] = json.loads(manifest.read_text())['archive_sha256']
    record['sources_lock_sha256'] = hashlib.sha256((ROOT/'sources.lock.json').read_bytes()).hexdigest()
    record['entry_audit'] = audit_entry(fd, args.preflight_only, args.native_el1)
    if args.bootimg:
        script = 'package-sheng-boot-v4.py' if args.boot_header == 4 else 'package-sheng-boot.py'
        command = ['python3', f'scripts/{script}', '--fixture', ROOT/'UniXNU/scripts/qemu-entry/bootshim-fixture.S']
        if args.boot_header == 4:
            command.extend(['--compression', args.compression])
            if args.boot_template:
                command.extend(['--boot-template', args.boot_template.resolve()])
        if not shutil.which('qemu-system-aarch64', path=env['PATH']):
            command.append('--skip-qemu')
        run(command, DEVICE, 'firmware-bootimg')
        report = 'report-v4.json' if args.boot_header == 4 else 'report.json'
        record['bootimg'] = json.loads((DEVICE/'build/sheng/boot'/report).read_text())
        if record['bootimg']['fd_sha256'] != record['sha256']:
            raise ValueError('packaged FD differs from the audited firmware')
    mode = 'native-el1' if args.native_el1 else 'preflight' if args.preflight_only else 'baseline'
    identity = record['bootimg']['container_sha256'] if args.bootimg else record['sha256']
    artifact_dir = ROOT/'out/firmware'/mode/identity
    artifact_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fd, artifact_dir/fd.name)
    record['artifacts'] = [str((artifact_dir/fd.name).relative_to(ROOT))]
    if args.bootimg:
        image = DEVICE/'build/sheng/boot'/('sheng-uefi-v4.img' if args.boot_header == 4 else 'sheng-uefi.img')
        shutil.copy2(image, artifact_dir/image.name)
        record['artifacts'].append(str((artifact_dir/image.name).relative_to(ROOT)))
    (artifact_dir/'build.json').write_text(json.dumps(record, indent=2)+'\n')
    (ROOT/'out/firmware-build.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
