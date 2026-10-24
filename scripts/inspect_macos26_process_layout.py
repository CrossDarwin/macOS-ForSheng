#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Derive bounded process-list offsets from the matching native kernel DWARF."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess

from native_macho import macho
from observe_macos26_kernel import identify, backed_offset


def member(text, name):
    matches = []
    for die in re.finditer(r'^0x[0-9a-f]+:( +)DW_TAG_member\n(.*?)(?=^0x|\Z)', text, re.M | re.S):
        if re.search(r'DW_AT_name\s+\("' + re.escape(name) + r'"\)', die[2]):
            location = re.search(r'DW_AT_data_member_location\s+\((0x[0-9a-f]+)\)', die[2])
            if location:
                matches.append((len(die[1]), int(location[1], 16)))
    depth = min((d for d, _ in matches), default=0)
    values = {value for d, value in matches if d == depth}
    if len(values) != 1:
        raise ValueError(f'no unique compiler offset for proc.{name}: {values}')
    return values.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--dwarfdump', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--threads', action='store_true')
    args = parser.parse_args()
    kernel, symbols, identity = identify(args.kernel_build)
    dwarf, = (args.kernel_build / 'kernel.development.sheng.dSYM/Contents/Resources/DWARF').iterdir()
    text = subprocess.check_output([args.dwarfdump, '--name=proc', '--show-children', dwarf],
                                   text=True, timeout=30)
    code = kernel.read_bytes()
    image = macho(code, identity['architecture'])
    at = backed_offset(image['segments'], symbols['_proc_name_address'], 12, len(code))
    bti, add, ret = struct.unpack_from('<3I', code, at)
    if bti != 0xd503245f or add & 0xffc003ff != 0x91000000 or ret != 0xd65f03c0:
        raise ValueError('unqualified compiled process-name accessor')
    offsets = dict(pid=member(text, 'p_pid'), stat=member(text, 'p_stat'),
                   next=member(text, 'p_list'), comm=(add >> 10) & 0xfff)
    if offsets['next'] != 0 or any(not 0 <= v < 65536 for v in offsets.values()):
        raise ValueError('unqualified allproc list layout')
    result = dict(kernel_uuid=identity['uuid'], kernel_sha256=identity['kernel_sha256'],
                  allproc=symbols['_allproc'], offsets=offsets, kernel_va_bits=47,
                  source='matching proc DWARF and compiled proc_name_address', read_only=True)
    if args.threads:
        types = {'proc': text}

        def field(kind, name):
            if kind not in types:
                types[kind] = subprocess.check_output([args.dwarfdump, '--name=' + kind,
                    '--show-children', dwarf], text=True, timeout=30)
            return member(types[kind], name)

        machine = field('thread', 'machine')
        result['threads'] = dict(proc_ro=field('proc', 'p_proc_ro'),
            proc_owner=field('proc_ro', 'pr_proc'), proc_task=field('proc_ro', 'pr_task'),
            task_threads=field('task', 'threads'), task_thread_count=field('task', 'thread_count'),
            thread_link=field('thread', 'task_threads'), thread_ro=field('thread', 't_tro'),
            thread_owner=field('thread_ro', 'tro_owner'), thread_task=field('thread_ro', 'tro_task'),
            thread_id=field('thread', 'thread_id'), thread_state=field('thread', 'state'),
            continuation=field('thread', 'continuation'), wait_event=field('thread', 'wait_event'),
            kernel_stack=field('thread', 'kernel_stack'),
            upcb=machine + field('machine_thread', 'upcb'),
            kstackptr=machine + field('machine_thread', 'kstackptr'),
            context=field('thread_kernel_state', 'machine') + field('arm_kernel_context', 'ss'),
            saved_fp=field('arm_kernel_saved_state', 'fp'),
            saved_lr=field('arm_kernel_saved_state', 'lr'), saved_sp=field('arm_kernel_saved_state', 'sp'))
        result['kernel_stack_size_symbol'] = symbols['_kernel_stack_size']
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
