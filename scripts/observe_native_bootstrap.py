#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Execute the linked XNU bootstrap at sheng's physical placement, stopping before C initialization."""
import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from observe_macos26_kernel import identify

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts/qemu-entry'))
from gdb_packets import Packets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--clang', type=Path, required=True)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    kernel, symbols, identity = identify(args.kernel_build.resolve())
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    base, args_pa, window = 0x881004000, 0x882a00000, 0x20000000
    va = 0xfffffe0007004000
    data = kernel.read_bytes()
    flat = out / 'kernel-flat.bin'
    with flat.open('wb') as stream:
        for segment in identity['segments']:
            if not segment['size']:
                continue
            offset = segment['va'] - va
            if offset < 0 or offset + segment['size'] > args_pa - base:
                raise ValueError('kernel overlaps the hardware boot argument placement')
            stream.seek(offset)
            stream.write(data[segment['fileoff']:segment['fileoff'] + segment['filesize']])
            if segment['size']:
                stream.seek(offset + segment['size'] - 1)
                if segment['size'] > segment['filesize']:
                    stream.write(b'\0')
    boot = bytearray(1152)
    struct.pack_into('<HH', boot, 0, 2, 2)
    struct.pack_into('<4Q', boot, 8, va, base, window, args_pa + 0x100000)
    # No device tree or framebuffer: stop before the first C instruction.
    (out / 'boot-args.bin').write_bytes(boot)
    entry = base + int(identity['entry_va'], 16) - va
    stub = out / 'entry.S'
    stub.write_text('.text\n.global _start\n_start:\n'
                    ' msr daifset, #15\n'
                    f' ldr x0, ={args_pa:#x}\n ldr x1, ={entry:#x}\n br x1\n')
    linker = out / 'entry.ld'
    linker.write_text('ENTRY(_start)\nSECTIONS { . = 0x40200000; .text : { *(.text*) } }\n')
    subprocess.run([str(args.clang.resolve()), '--target=aarch64-none-elf', '-nostdlib',
                    '-fuse-ld=lld', '-Wl,-T,' + str(linker), str(stub),
                    '-o', str(out / 'entry.elf')], check=True, timeout=30)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    command = [str(args.qemu.resolve()), '-M', 'virt,virtualization=off,secure=off,gic-version=3',
               '-cpu', 'cortex-a710', '-m', '34816', '-nodefaults', '-display', 'none',
               '-serial', 'none', '-monitor', 'none', '-no-reboot',
               '-device', f'loader,file={out}/entry.elf,cpu-num=0',
               '-device', f'loader,file={flat},addr={base:#x},force-raw=on',
               '-device', f'loader,file={out}/boot-args.bin,addr={args_pa:#x},force-raw=on',
               '-gdb', f'tcp:127.0.0.1:{port}', '-S']
    env = dict(os.environ, LD_LIBRARY_PATH=str(args.qemu.resolve().parent.parent / 'lib/x86_64-linux-gnu'))
    (out / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
    with (out / 'qemu.log').open('w') as log:
        proc = subprocess.Popen(command, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    connection = socket.create_connection(('127.0.0.1', port), timeout=.2)
                    break
                except OSError:
                    if proc.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('QEMU did not start; inspect qemu.log') from None
                    time.sleep(.05)
            with connection:
                connection.settimeout(15)
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                packets = Packets(connection)
                request = packets.request
                checkpoint = symbols['_arm_init']
                if request(f'Z1,{checkpoint:x},4') != 'OK':
                    raise RuntimeError('QEMU refused the bootstrap breakpoint')
                timed_out = False
                try:
                    request('c')
                except TimeoutError:
                    timed_out = True
                    request(None)
                registers = bytes.fromhex(request('g'))
                core = struct.unpack('<33Q', registers[:264])
                result = dict(uuid=identity['uuid'], kernel_pa=hex(base), boot_args_pa=hex(args_pa),
                              pc=hex(core[32]), sp=hex(core[31]), x0=hex(core[0]),
                              timed_out=timed_out, hardware_executed=False, c_initialization_executed=False)

                def feature(name: str) -> ET.Element:
                    offset, content = 0, ''
                    while True:
                        chunk = request(f'qXfer:features:read:{name}:{offset:x},1000')
                        if not chunk or chunk[0] not in 'lm':
                            raise RuntimeError('invalid GDB target description')
                        content += chunk[1:]
                        offset += len(chunk) - 1
                        if chunk[0] == 'l':
                            if 'xi:include' in content and 'xmlns:xi=' not in content:
                                content = content.replace('<target', '<target xmlns:xi="http://www.w3.org/2001/XInclude"', 1)
                            return ET.fromstring(content)
                        if offset > 1024 * 1024:
                            raise RuntimeError('GDB target description exceeds bound')

                for include in feature('target.xml').findall('{http://www.w3.org/2001/XInclude}include'):
                    for reg in feature(include.attrib['href']).findall('reg'):
                        name = reg.attrib['name']
                        if name in ('TCR_EL1', 'SCTLR_EL1', 'TTBR0_EL1', 'TTBR1_EL1',
                                    'ESR_EL1', 'ELR_EL1', 'FAR_EL1', 'VBAR_EL1'):
                            value = bytes.fromhex(request(f'p{int(reg.attrib["regnum"]):x}'))
                            result[name] = hex(int.from_bytes(value, 'little'))
                reached = not timed_out and core[32] == checkpoint
                result['reached_c_entry'] = reached
                if reached:
                    result['entry_instruction'] = request(f'm{checkpoint:x},4')
                    expected = None
                    for segment in identity['segments']:
                        if segment['va'] <= checkpoint < segment['va'] + segment['filesize']:
                            offset = segment['fileoff'] + checkpoint - segment['va']
                            expected = data[offset:offset + 4].hex()
                    reached = result['entry_instruction'] == expected and core[0] == va + args_pa - base
                    result['instruction_and_args_match'] = reached
                (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps(result), flush=True)
                if not reached:
                    raise RuntimeError('high physical bootstrap did not reach the identified C entry')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            # Flat files and the stub are reproducible; retain only diagnostic evidence.
            flat.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
