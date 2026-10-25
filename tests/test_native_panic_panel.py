# SPDX-License-Identifier: MIT
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts/qemu-entry'))
from gdb_packets import Packets


class NativePanicPanel(unittest.TestCase):
    def test_busy_writer_keeps_full_panic_and_disjoint_pixels(self):
        clang = os.environ.get('CLANG', shutil.which('clang'))
        qemu = ROOT / 'out/qemu-root/usr/bin/qemu-system-aarch64'
        font = ROOT / 'sources/macos26/xnu/osfmk/console/iso_font.c'
        if not clang or not qemu.exists() or not font.exists():
            self.skipTest('requires clang, QEMU and the pinned XNU font')
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            for source, target in (('retained_log.h', 'pe_sheng_log.h'),
                                   ('panel_console.h', 'pe_sheng_panel.h'), ('vm_trace.h', 'vm_trace.h')):
                shutil.copy2(ROOT / 'platform/sheng/macos26/log' / source, work / target)
            shutil.copy2(font, work / 'pe_sheng_font.h')
            (work / 'entry.S').write_text('.text\n.global _start\n_start:\n msr daifset,#15\n'
                ' adr x0, vectors\n msr vbar_el1,x0\n isb\n'
                ' ldr x0,=0x40300000\n mov sp,x0\n bl run_trace\n.global done\ndone:\n b done\n'
                '.balign 2048\nvectors:\n.rept 16\n b trap\n.space 124\n.endr\n'
                'trap:\n mrs x0,elr_el1\n mrs x1,esr_el1\n mrs x2,far_el1\n'
                '.global fatal\nfatal:\n b fatal\n')
            (work / 'runtime.ld').write_text('ENTRY(_start)\nSECTIONS { . = 0x40200000; '
                '.text : { *(.text*) } .data : { *(.data*) } .bss : { *(.bss*) } }\n')
            compiler = Path(clang).resolve()
            subprocess.run([str(compiler), '--target=aarch64-none-elf', '-O2', '-ffreestanding',
                '-fno-stack-protector', '-mgeneral-regs-only', '-mstrict-align', '-Wall', '-Wextra', '-Werror', '-I' + str(work),
                '-I' + str(ROOT / 'sources/macos26/xnu/osfmk'), '-nostdlib', '-fuse-ld=lld',
                '-Wl,-T,' + str(work / 'runtime.ld'), str(work / 'entry.S'),
                str(ROOT / 'tests/native_panic_panel.c'), '-o', str(work / 'runtime.elf')], check=True, timeout=30)
            symbols = {parts[2]: int(parts[0], 16) for line in subprocess.check_output(
                [str(compiler.parent / 'llvm-nm'), str(work / 'runtime.elf')], text=True).splitlines()
                if len(parts := line.split()) == 3}
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            env = dict(os.environ, LD_LIBRARY_PATH=str(ROOT / 'out/qemu-root/usr/lib/x86_64-linux-gnu'))
            with (work / 'qemu.log').open('w') as log:
                process = subprocess.Popen([str(qemu), '-M', 'virt,virtualization=off,secure=off',
                    '-cpu', 'cortex-a710', '-m', '256', '-nodefaults', '-display', 'none',
                    '-serial', 'none', '-monitor', 'none', '-device',
                    f'loader,file={work}/runtime.elf,cpu-num=0', '-gdb', f'tcp:127.0.0.1:{port}', '-S'],
                    env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            connection = socket.create_connection(('127.0.0.1', port), timeout=.2)
                            break
                        except OSError:
                            if time.monotonic() > deadline:
                                raise RuntimeError('QEMU startup failed: ' + (work / 'qemu.log').read_text())
                            time.sleep(.05)
                    with connection:
                        connection.settimeout(10)
                        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        request = Packets(connection).request

                        def memory(address, size):
                            return b''.join(bytes.fromhex(request(f'm{address + offset:x},{min(4096, size - offset):x}'))
                                for offset in range(0, size, 4096))

                        def number(name):
                            return int.from_bytes(memory(symbols[name], 8), 'little')

                        self.assertEqual(request(f'Z1,{symbols["panic_ready"]:x},4'), 'OK')
                        self.assertEqual(request(f'Z1,{symbols["fatal"]:x},4'), 'OK')
                        try:
                            stopped = request('c')
                        except TimeoutError as error:
                            connection.sendall(b'\x03')
                            Packets(connection).receive()
                            registers = bytes.fromhex(request('g'))
                            pc = int.from_bytes(registers[32 * 8:33 * 8], 'little')
                            near = sorted((address, name) for name, address in symbols.items() if address <= pc)[-5:]
                            raise RuntimeError(f'guest stopped at pc={pc:x}, symbols={near}') from error
                        self.assertTrue(stopped.startswith(('T05', 'S05')))
                        registers = bytes.fromhex(request('g'))
                        if int.from_bytes(registers[32 * 8:33 * 8], 'little') == symbols['fatal']:
                            values = [int.from_bytes(registers[n * 8:(n + 1) * 8], 'little') for n in range(3)]
                            near = sorted((address, name) for name, address in symbols.items() if address <= values[0])[-4:]
                            self.fail(f'ELR/ESR/FAR={values}, symbols={near}')
                        self.assertEqual(number('panic_test_checks'), 11)
                        self.assertEqual(number('sheng_panel_bound_rows'), 24)
                        self.assertEqual(number('sheng_panic_panel_bound_rows'), 16)
                        text = memory(symbols['sheng_first_panic_text'], 4096)
                        self.assertIn(b'PAYLOAD_END_AFTER_511_BYTES', text)
                        # 标题和正文按真实字体逐像素核对，不能只靠ready变量
                        base = 0x44000000 + (608 + 64 + 24 * 32) * 12192 + 896
                        before = memory(base, 16 * 32 * 12192)
                        glyphs = memory(symbols['sheng_panel_font'], 4096)
                        for line, expected in enumerate(('SHENG - PANIC DETAIL', 'UFS ROOT FAILURE: root window volume not found')):
                            for column, char in enumerate(expected):
                                for y in range(32):
                                    bits = glyphs[ord(char) * 16 + y // 2]
                                    for x in range(16):
                                        offset = (line * 32 + y) * 12192 + column * 64 + x * 4
                                        pixel = int.from_bytes(before[offset:offset + 4], 'little')
                                        self.assertEqual(pixel, 0xffffffff if bits & (1 << (x // 2)) else 0xff000000)
                        self.assertEqual(request(f'z1,{symbols["panic_ready"]:x},4'), 'OK')
                        self.assertEqual(request(f'Z1,{symbols["done"]:x},4'), 'OK')
                        self.assertTrue(request('c').startswith(('T05', 'S05')))
                        self.assertEqual(number('panic_test_checks'), 15)
                        self.assertEqual(before, memory(base, len(before)))
                        output = ROOT / 'out/native-panic-writer-validation'
                        output.mkdir(parents=True, exist_ok=True)
                        (output / 'result.json').write_text(json.dumps(dict(
                            writer_not_stolen=True, first_panic_text_preserved=True,
                            actual_font_pixels_verified=True, ordinary_tail_lines=80,
                            panic_rows=16, normal_rows=24, hardware_executed=False), indent=2) + '\n')
                        from PIL import Image
                        raw = memory(0x44000000 + 608 * 12192 + 896, (64 + 40 * 32) * 12192)
                        Image.frombytes('RGBX', (3048, 1344), raw, 'raw', 'BGRX').convert('RGB').crop(
                            (0, 0, 1408, 1344)).save(output / 'screen.png')
                finally:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
