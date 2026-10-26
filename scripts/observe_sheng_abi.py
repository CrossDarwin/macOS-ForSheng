#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replay the original-component ABI observations through real QEMU UEFI."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from stage_sheng_dependencies import ROOT, stage, sha

sys.path.insert(0, str(ROOT / 'UniXNU/kits/NativePrelink'))
from native_prelink import macho


def symbols(path: Path) -> dict:
    data = path.read_bytes()
    parsed = macho(data)
    command = next(at for kind, at, _ in parsed['commands'] if kind == 2)
    offset, count, strings, string_bytes = struct.unpack_from('<4I', data, command + 8)
    if offset + count * 16 > len(data) or strings + string_bytes > len(data):
        raise ValueError('source kernel symbol table exceeds file')
    names = data[strings:strings + string_bytes]
    found = {}
    for index in range(count):
        name, kind, _, _, address = struct.unpack_from('<IBBHQ', data, offset + 16 * index)
        if kind & 0xe0 or kind & 0xe != 0xe:
            continue
        end = names.find(b'\0', name)
        if end < 0:
            raise ValueError('unterminated source kernel symbol')
        found[names[name:end].decode()] = address
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'out/sheng-abi-replay')
    parser.add_argument('--firmware', type=Path, help='QEMU AArch64 UEFI code FD')
    parser.add_argument('--timeout', type=int, default=60)
    args = parser.parse_args()
    if not 15 <= args.timeout <= 180:
        parser.error('timeout must be between 15 and 180 seconds per observation')
    output = args.output.resolve()
    if output.exists():
        raise ValueError('use a new output directory to preserve previous observations')
    stage(ROOT / 'out/sheng-xnu/work/sheng/tree')
    pin = json.loads((ROOT / 'config/sheng-reconstructed-inputs.json').read_text())
    inputs = ROOT / 'private/build-inputs' / (pin['release'] + '-extracted')
    baseline = json.loads((ROOT / 'config/sheng-baseline.json').read_text())['prelink']
    output.mkdir(parents=True)
    candidate = output / 'candidate.macho'
    command = [sys.executable, str(ROOT / 'UniXNU/kits/NativePrelink/emit_prelink.py'),
               '--kernel', str(inputs / 'source-kernel.macho'), '--prelinked', str(inputs / 'kernelcache.macho'),
               '--slide=' + baseline['slide'], '--output', str(candidate),
               '--early-security-init', baseline['early_security_init']]
    for root in baseline['roots']:
        command += ['--root', root]
    with (output / 'prelink.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    if sha(candidate) != pin['candidate_sha256']:
        raise ValueError('replayed prelink bytes differ from the observed candidate')
    addresses = symbols(inputs / 'source-kernel.macho')
    original_storage_meta = 0xfffffff006add1d0
    service_meta = addresses['__ZN9IOService10gMetaClassE']
    records = {}
    for case in ('storage', 'legacy'):
        fixture = output / case
        esp = fixture / 'esp'
        payload = esp / 'EFI/UniXNU/Payloads'
        payload.mkdir(parents=True)
        (esp / 'EFI/BOOT').mkdir()
        shutil.copy2(inputs / 'loader/BOOTAA64.EFI', esp / 'EFI/BOOT/BOOTAA64.EFI')
        shutil.copy2(inputs / 'loader/DarwinBoot.efi', payload / 'DarwinBoot.efi')
        shutil.copy2(candidate, payload / 'kernel.macho')
        config = esp / 'EFI/UniXNU/unixnu.toml'
        text = (inputs / 'qemu/base-config.toml').read_text()
        if case == 'legacy':
            text = text.replace('cpus=1', 'cpus=1 offline-mobile-graphics-load=1')
        config.write_text(text)
        dt = payload / 'kernel.macho.adt'
        subprocess.run([sys.executable, str(ROOT / 'UniXNU/scripts/qemu-entry/make-dt.py'),
                        '--output', str(dt), '--dram-size', '0x40000000', '--owned-memory-size', '0x20000000',
                        '--armvirt', '--armcpu', '--platform-compatible', 'xiaomi,sheng',
                        '--qemu-vmm-present', '--nvram-proxy', '--crypto-hash-method', 'sha2-384',
                        '--amfi-platform-only'], check=True)
        target = addresses['_bsd_init' if case == 'storage' else '__ZN11OSMetaClassC2EPKcPKS_j']
        command = [sys.executable, str(ROOT / 'UniXNU/scripts/qemu-entry/gdb-stop.py'), hex(target),
                   '--fixture', str(fixture), '--esp', str(esp), '--kernel', str(candidate),
                   '--system-registers', '--gic-version', '3', '--qemu-memory-mib', '1024',
                   '--timeout', str(args.timeout), '--also-stop', hex(addresses['_panic'])]
        if args.firmware:
            command += ['--firmware', str(args.firmware.resolve())]
        if case == 'storage':
            command += ['--read-memory', f'{original_storage_meta:x}:50', '--read-memory', f'{service_meta:x}:50']
        else:
            command += ['--entry-kernel-bytes-field', '1:0:' + b'IOMobileFramebufferLegacy\0'.hex(),
                        '--entry-max-skips', '4096', '--finish-function', '--read-entry-region', '0:0:50']
        (fixture / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        with (fixture / 'observer.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        snapshot_path = fixture / 'gdb-stop.json'
        snapshot = json.loads(snapshot_path.read_text())
        if snapshot['kernel_sha256'] != pin['candidate_sha256'] or snapshot['bounded_timeout_interrupted']:
            raise ValueError(f'{case}: actual matching bounded observation required')
        registers = {name: int(value, 16) for name, value in snapshot['system_registers'].items()}
        if (registers['TCR_EL1'] >> 14 & 3 != 0 or registers['TCR_EL1'] >> 30 & 3 != 2 or
                not registers['SCTLR_EL1'] & 1 or not registers['TTBR0_EL1'] or not registers['TTBR1_EL1']):
            raise ValueError(f'{case}: actual 4K translation required')
        if case == 'storage':
            block = bytes.fromhex(snapshot['memory'][f'{original_storage_meta:x}:50'])
            service = bytes.fromhex(snapshot['memory'][f'{service_meta:x}:50'])
            if (int(snapshot['pc'], 16) != target or struct.unpack_from('<Q', block, 16)[0] != service_meta or
                    struct.unpack_from('<I', block, 32)[0] != 0x90 or
                    struct.unpack_from('<I', service, 32)[0] != 0x88):
                raise ValueError('actual original storage metaclass/parent/size mismatch')
        else:
            arguments = [int(value, 16) for value in snapshot['function_entry_arguments']]
            if (not snapshot['function_return_stack_matched'] or arguments[0] != 0xfffffff006b35940 or
                    arguments[2:4] != [0xfffffff006b31400, 0x18a0] or
                    snapshot['entry_kernel_bytes_match']['bytes'] != b'IOMobileFramebufferLegacy\0'.hex()):
                raise ValueError('actual Legacy constructor identity/parent/size mismatch')
        records[case] = dict(snapshot_sha256=sha(snapshot_path), dt_sha256=sha(dt), config_sha256=sha(config),
                             command_sha256=sha(fixture / 'command.json'), passed=True)
        print('PASS actual QEMU observation:', case, flush=True)
    record = dict(candidate_sha256=sha(candidate), input_archive_sha256=pin['sha256'],
                  qemu_version=subprocess.check_output(['qemu-system-aarch64', '--version'], text=True).splitlines()[0],
                  cases=records, hardware_tested=False, macos_userspace_qualified=False)
    if args.firmware:
        record['firmware_sha256'] = sha(args.firmware)
    (output / 'verification.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
