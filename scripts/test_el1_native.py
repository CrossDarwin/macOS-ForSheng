#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute the EL1 assembly in QEMU with a genuine 16K walk and a 4K fallback control."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clang', type=Path, required=True)
    p.add_argument('--qemu', type=Path, required=True)
    args = p.parse_args()
    source = ROOT / 'probes/el1-native'
    out = ROOT / 'out/el1-native-qemu'
    out.mkdir(parents=True, exist_ok=True)
    linker = out / 'probe.ld'
    linker.write_text('ENTRY(_start)\nSECTIONS { . = 0x80080000; .text : { *(.text*) } '
                      '.rodata : { *(.rodata*) } .data : { *(.data*) } '
                      '.bss : { *(.bss*) *(COMMON) } }\n')
    env = dict(os.environ)
    libraries = args.qemu.resolve().parent.parent / 'lib/x86_64-linux-gnu'
    if libraries.is_dir():
        env['LD_LIBRARY_PATH'] = str(libraries) + ':' + env.get('LD_LIBRARY_PATH', '')
    records = []
    for name, define in (('native-16k', None), ('fallback-4k', 'SHENG_GRANULE_FORCE_4K'),
                         ('exception-recovery', 'SHENG_GRANULE_INJECT_FAULT')):
        binary = out / (name + '.elf')
        command = [str(args.clang), '--target=aarch64-none-elf', '-march=armv8.3-a',
                   '-ffreestanding', '-fno-builtin', '-mgeneral-regs-only', '-O2', '-nostdlib',
                   '-fuse-ld=lld', '-Wl,-T,' + str(linker), '-o', str(binary)]
        if define:
            command += ['-D' + define + '=1']
        command += [str(source / name) for name in ('qemu-entry.S', 'qemu.c', 'native.S')]
        subprocess.run(command, check=True, timeout=60)
        command = [str(args.qemu), '-M', 'virt,virtualization=off', '-cpu', 'max', '-m', '3G',
                   '-nodefaults', '-display', 'none', '-serial', 'none', '-monitor', 'none',
                   '-semihosting-config', 'enable=on,target=native',
                   '-device', 'loader,file=' + str(binary) + ',cpu-num=0']
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired as error:
            (out / (name + '.log')).write_bytes((error.stdout or b'') + (error.stderr or b''))
            raise
        log = result.stdout + result.stderr
        (out / (name + '.log')).write_text(log)
        print(log, end='', flush=True)
        records.append(dict(case=name, returncode=result.returncode, output=log))
        (out / 'results.json').write_text(json.dumps(dict(cases=records, sheng_hardware_executed=False), indent=2)+'\n')
        if result.returncode or 'PASS PAC IA IB DA DB GA switch and restore' not in log:
            raise RuntimeError(f'{name}: the actual EL1 probe did not complete')


if __name__ == '__main__':
    main()
