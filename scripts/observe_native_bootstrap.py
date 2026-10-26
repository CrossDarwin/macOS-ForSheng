#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
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
    parser.add_argument('--trap-debug-unlock', action='store_true',
                        help='QEMU only: run at EL1 under an EL2 host that traps OS debug accesses')
    parser.add_argument('--expect-debug-trap', action='store_true',
                        help='Accept only an actual EL2 trap on OSLAR_EL1 as the regression control')
    parser.add_argument('--framebuffer-trace', action='store_true',
                        help='Provide sheng framebuffer geometry in guest RAM and require real post-MMU pixels')
    args = parser.parse_args()
    if args.expect_debug_trap and not args.trap_debug_unlock:
        parser.error('--expect-debug-trap requires --trap-debug-unlock')
    kernel, symbols, identity = identify(args.kernel_build.resolve())
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    base, window = 0x881004000, 0x20000000
    va = 0xfffffe0007004000
    # Match DarwinBoot's ALIGN_VALUE(Address + Kernel.End - Kernel.Base, SIZE_16KB).
    end = max(segment['va'] + segment['size'] for segment in identity['segments'] if segment['size'])
    args_pa = (base + end - va + 16383) & ~16383
    if args_pa + 0x100000 > base + window:
        raise ValueError('kernel and bootstrap inputs exceed the owned window')
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
    if args.framebuffer_trace:
        struct.pack_into('<6Q', boot, 40, 0xb8000000, 0, 12192, 3048, 2032, 32)
    # No device tree: stop before the first C instruction.
    (out / 'boot-args.bin').write_bytes(boot)
    entry = base + int(identity['entry_va'], 16) - va
    stub = out / 'entry.S'
    setup = ''
    transfer = ' br x1\n'
    if args.trap_debug_unlock:
        setup = (' adr x0, el2_vectors\n msr vbar_el2, x0\n'
                 ' ldr x0, =0x30080000000\n msr hcr_el2, x0\n'
                 ' mov x0, #0x400\n msr mdcr_el2, x0\n'
                 ' msr cptr_el2, xzr\n'
                 ' ldr x0, =0x30d00808\n msr sctlr_el1, x0\n'
                 ' ldr x0, =0x40210000\n msr sp_el1, x0\n'
                 ' mov x0, #0x3c5\n msr spsr_el2, x0\n')
        transfer = ' msr elr_el2, x1\n isb\n eret\n'
    stub.write_text('.text\n.global _start\n_start:\n msr daifset, #15\n' + setup +
                    f' ldr x0, ={args_pa:#x}\n ldr x1, ={entry:#x}\n' + transfer +
                    '.balign 2048\nel2_vectors:\n.rept 16\n b el2_trap\n.balign 128\n.endr\n'
                    '.global el2_trap\nel2_trap:\n b el2_trap\n')
    linker = out / 'entry.ld'
    linker.write_text('ENTRY(_start)\nSECTIONS { . = 0x40200000; .text : { *(.text*) } }\n')
    subprocess.run([str(args.clang.resolve()), '--target=aarch64-none-elf', '-nostdlib',
                    '-fuse-ld=lld', '-Wl,-T,' + str(linker), str(stub),
                    '-o', str(out / 'entry.elf')], check=True, timeout=30)
    elf_symbols = {line.split()[2]: int(line.split()[0], 16) for line in
                   subprocess.check_output([str(args.clang.resolve().parent / 'llvm-nm'),
                                            str(out / 'entry.elf')], text=True).splitlines()
                   if len(line.split()) == 3}
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    virtualization = 'on' if args.trap_debug_unlock else 'off'
    command = [str(args.qemu.resolve()), '-M', f'virt,virtualization={virtualization},secure=off,gic-version=3',
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
                if args.trap_debug_unlock and request(f'Z1,{elf_symbols["el2_trap"]:x},4') != 'OK':
                    raise RuntimeError('QEMU refused the EL2 trap breakpoint')
                timed_out = False
                try:
                    request('c')
                except TimeoutError:
                    timed_out = True
                    request(None)
                registers = bytes.fromhex(request('g'))
                core = struct.unpack('<33Q', registers[:264])
                result = dict(uuid=identity['uuid'], kernel_sha256=identity['kernel_sha256'],
                              kernel_pa=hex(base), boot_args_pa=hex(args_pa),
                              pc=hex(core[32]), sp=hex(core[31]), x0=hex(core[0]),
                              el2_debug_trap_policy_enabled=args.trap_debug_unlock,
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
                                    'ESR_EL1', 'ELR_EL1', 'FAR_EL1', 'VBAR_EL1',
                                    'ESR_EL2', 'ELR_EL2', 'FAR_EL2', 'MDCR_EL2', 'HCR_EL2'):
                            value = bytes.fromhex(request(f'p{int(reg.attrib["regnum"]):x}'))
                            result[name] = hex(int.from_bytes(value, 'little'))
                reached = not timed_out and core[32] == checkpoint
                result['reached_c_entry'] = reached
                if args.trap_debug_unlock and int(result.get('MDCR_EL2', '0'), 16) != 0x400:
                    raise RuntimeError('the QEMU host did not retain the requested debug trap policy')
                if args.expect_debug_trap:
                    fault_pa = int(result.get('ELR_EL2', '0'), 16)
                    trapped = not timed_out and core[32] == elf_symbols['el2_trap']
                    instruction = request(f'm{fault_pa:x},4') if trapped else ''
                    result['trapped_instruction'] = instruction
                    reached = (trapped and int(result['ESR_EL2'], 16) >> 26 == 0x18
                               and instruction == '9f1010d5')
                    result['expected_oslar_trap_captured'] = reached
                elif reached:
                    result['entry_instruction'] = request(f'm{checkpoint:x},4')
                    expected = None
                    for segment in identity['segments']:
                        if segment['va'] <= checkpoint < segment['va'] + segment['filesize']:
                            offset = segment['fileoff'] + checkpoint - segment['va']
                            expected = data[offset:offset + 4].hex()
                    reached = result['entry_instruction'] == expected and core[0] == va + args_pa - base
                    result['instruction_and_args_match'] = reached
                    native_build = json.loads((kernel.parent / 'build.json').read_text())
                    if native_build.get('bootstrap_trace_source_sha256'):
                        stage = int.from_bytes(bytes.fromhex(request(
                            f'm{symbols["_sheng_early_exception_record"]+184:x},8')), 'little')
                        result['bootstrap_stage'] = hex(stage)
                        reached = reached and stage == (15 if native_build.get('bootstrap_post_mmu_stages') else 12)
                    if args.framebuffer_trace:
                        ready = int.from_bytes(bytes.fromhex(request(
                            f'm{symbols["_sheng_bootstrap_fb_trace_ready"]:x},8')), 'little')
                        result['post_mmu_framebuffer_mapping_ready'] = ready == 1
                        pixels = []
                        for index in range(16):
                            pixel = 0xb8000000 + 568 * 12192 + (224 + 24 * index) * 4
                            pixels.append(hex(int.from_bytes(bytes.fromhex(request(f'm{pixel:x},4')), 'little')))
                        result['actual_stage_pixels'] = pixels
                        reached = reached and ready == 1 and pixels == ['0xff00ff00'] * 16
                (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
                print(json.dumps(result), flush=True)
                if not reached:
                    raise RuntimeError('bootstrap outcome differs from the requested C-entry/debug-trap observation')
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
