#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Observe the linked native macOS 26 kernel through UniXNU's QEMU entry path."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid

from observe_sheng_abi import symbols

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'UniXNU/kits/NativePrelink'))
from native_prelink import macho, backed_offset


def identify(build_dir: Path) -> tuple[Path, dict, dict]:
    build = json.loads((build_dir / 'build.json').read_text())
    kernel = build_dir / 'kernel.development.sheng'
    data = kernel.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if (build.get('xnu') != '12377.121.6' or build.get('build') != '25F71'
            or build.get('machine') != 'SHENG' or not build.get('executable_kernel_built')
            or digest != build.get('executable_kernel_sha256')):
        raise ValueError('requires the actual linked SHENG macOS 26.5 artifact')
    image = macho(data)
    if image['kind'] != 2:
        raise ValueError('requires an executable kernel, not its source archive')
    entry = deployment = identity = None
    for kind, offset, size in image['commands']:
        if kind == 5:
            if size != 288 or struct.unpack_from('<II', data, offset + 8) != (6, 68):
                raise ValueError('unsupported ARM64 UNIXTHREAD state')
            entry = struct.unpack_from('<Q', data, offset + 272)[0]
        elif kind == 0x32:
            deployment = struct.unpack_from('<II', data, offset + 8)
        elif kind == 0x1b:
            identity = str(uuid.UUID(bytes=data[offset + 8:offset + 24])).upper()
    if deployment != (1, 0x1a0500) or entry is None or identity is None:
        raise ValueError('kernel lacks its macOS 26.5 deployment, entry or UUID')
    for segment in image['segments']:
        if segment['fileoff'] + segment['filesize'] > len(data):
            raise ValueError('kernel segment exceeds its backing file')
    backed_offset(image['segments'], entry, 4, len(data))
    if not any(s['initprot'] & 4 and s['va'] <= entry < s['va'] + s['filesize']
               for s in image['segments']):
        raise ValueError('entry is not in an executable file-backed segment')
    addresses = symbols(kernel)
    if entry != addresses.get('__start') or min(s['va'] for s in image['segments']
            if s['size']) != 0xfffffe0007004000:
        raise ValueError('entry or linked base differs from the native SHENG layout')
    dwarfs = list((build_dir / 'kernel.development.sheng.dSYM/Contents/Resources/DWARF').iterdir())
    if len(dwarfs) != 1 or not dwarfs[0].is_file():
        raise ValueError('requires exactly one linked kernel DWARF image')
    dwarf_data = dwarfs[0].read_bytes()
    dwarf_image = macho(dwarf_data)
    dwarf_ids = [str(uuid.UUID(bytes=dwarf_data[at + 8:at + 24])).upper()
                 for kind, at, _ in dwarf_image['commands'] if kind == 0x1b]
    if dwarf_ids != [identity]:
        raise ValueError('debug symbols do not belong to this linked kernel')
    return kernel, addresses, dict(kernel_sha256=digest, uuid=identity,
        entry_va=hex(entry), segments=image['segments'], deployment='macOS 26.5',
        hardware_executed=False, userland_started=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', choices=('arm_init', 'arm_vm_init',
                        'PE_create_console', 'bsd_init', 'IOFindBSDRoot'), default='arm_init')
    parser.add_argument('--timeout', type=int, default=60, metavar='SECONDS')
    args = parser.parse_args()
    if not 15 <= args.timeout <= 180:
        parser.error('--timeout must be between 15 and 180 seconds')
    kernel, addresses, record = identify(args.kernel_build.resolve())
    checkpoint = addresses['_' + args.checkpoint]
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'kernel-layout.json').write_text(json.dumps(record, indent=2) + '\n')
    pin = json.loads((ROOT / 'config/sheng-reconstructed-inputs.json').read_text())
    inputs = ROOT / 'private/build-inputs' / (pin['release'] + '-extracted')
    esp = args.output / 'esp'
    payload = esp / 'EFI/UniXNU/Payloads'
    payload.mkdir(parents=True)
    (esp / 'EFI/BOOT').mkdir()
    shutil.copy2(inputs / 'loader/BOOTAA64.EFI', esp / 'EFI/BOOT/BOOTAA64.EFI')
    shutil.copy2(inputs / 'loader/DarwinBoot.efi', payload / 'DarwinBoot.efi')
    shutil.copy2(kernel, payload / 'kernel.macho')
    (esp / 'EFI/UniXNU/unixnu.toml').write_text(
        'version = 1\n[boot]\ntimeout = 1\ndefault = "native26"\n'
        '[kits]\nautoload = false\n[[driver]]\npath = "Payloads/DarwinBoot.efi"\n'
        '[[entry]]\nid = "native26"\ntitle = "Native SHENG macOS 26 - kernel entry"\n'
        'type = "xnu"\npath = "Payloads/kernel.macho"\n'
        'args = "-v debug=0x14e keepsyms=1 cpus=1 -enable_kprintf_spam"\n')
    subprocess.run([sys.executable, ROOT / 'UniXNU/scripts/qemu-entry/make-dt.py',
                    '--output', payload / 'kernel.macho.adt', '--dram-size', '0x40000000',
                    '--owned-memory-size', '0x20000000', '--armvirt', '--armcpu',
                    '--platform-compatible', 'xiaomi,sheng', '--qemu-vmm-present',
                    '--nvram-proxy', '--crypto-hash-method', 'sha2-384',
                    '--amfi-platform-only'], check=True)
    command = [sys.executable, ROOT / 'UniXNU/scripts/qemu-entry/gdb-stop.py', hex(checkpoint),
               '--fixture', args.output, '--esp', esp, '--kernel', kernel,
               '--firmware', args.firmware.resolve(), '--gic-version', '3',
               '--qemu-memory-mib', '1024', '--timeout', str(args.timeout),
               '--system-registers', '--qemu-ramfb', '--also-stop', hex(addresses['_panic'])]
    (args.output / 'command.json').write_text(json.dumps([str(x) for x in command], indent=2) + '\n')
    log_requests = []
    if '_sheng_log_buffer' in addresses:
        from decode_native_log import SIZE
        base = addresses['_sheng_log_buffer']
        for offset in range(0, SIZE, 4096):
            request = f'{base + offset:x}:{min(4096, SIZE - offset):x}'
            log_requests.append(request)
            command += ['--read-memory', request]
        (args.output / 'command.json').write_text(json.dumps([str(x) for x in command], indent=2) + '\n')
    with (args.output / 'observer.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    snapshot = json.loads((args.output / 'gdb-stop.json').read_text())
    if log_requests:
        from decode_native_log import decode
        raw = b''.join(bytes.fromhex(snapshot['memory'][key]) for key in log_requests)
        (args.output / 'console.bin').write_bytes(raw)
        text, console = decode(raw, record['uuid'])
        (args.output / 'console.txt').write_bytes(text)
        (args.output / 'console.json').write_text(json.dumps(console, indent=2) + '\n')
    regs = {name: int(value, 16) for name, value in snapshot['system_registers'].items()}
    tcr = regs['TCR_EL1']
    passed = (not snapshot['bounded_timeout_interrupted'] and int(snapshot['pc'], 16) == checkpoint
              and tcr >> 14 & 3 == 2 and tcr >> 30 & 3 == 1
              and tcr & 63 == 17 and tcr >> 16 & 63 == 17 and regs['SCTLR_EL1'] & 1)
    record.update(checkpoint=args.checkpoint, checkpoint_va=hex(checkpoint),
                  reached=bool(passed), snapshot='gdb-stop.json')
    (args.output / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    if not passed:
        raise RuntimeError('kernel did not reach the requested checkpoint with 16K / 47-bit translation; inspect saved registers')
    print(f'PASS {args.checkpoint}: actual native kernel, 16K / 47-bit translation; QEMU only')


if __name__ == '__main__':
    main()
