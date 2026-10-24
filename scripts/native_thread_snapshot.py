# SPDX-License-Identifier: MIT
"""Read bounded kernel thread frames; never changes guest state or authenticates PAC."""
import struct


def capture(packet, processes, plan):
    layout = plan['threads']
    if any(not isinstance(v, int) or not 0 <= v < 65536 for v in layout.values()):
        raise ValueError('invalid compiler thread offsets')
    mask = (1 << plan['kernel_va_bits']) - 1
    kernel_base = (1 << 64) - (1 << plan['kernel_va_bits'])

    def canonical(raw):
        return (raw & mask) | kernel_base if raw else 0

    def read(address, count):
        if not kernel_base <= address < (1 << 64) - count or not 0 < count <= 304:
            raise ValueError('invalid bounded kernel extent')
        raw = packet(f'm{address:x},{count:x}')
        if raw.startswith('E') or len(raw) != count * 2:
            raise ValueError('kernel memory unavailable')
        return bytes.fromhex(raw)

    def word(address, count=8):
        return int.from_bytes(read(address, count), 'little')

    def pointer(address):
        return canonical(word(address))

    stack_size = word(plan['kernel_stack_size_symbol'])
    if not 16384 <= stack_size <= 262144 or stack_size & (stack_size - 1):
        raise ValueError('invalid actual kernel stack size')
    results = []
    for proc in [p for p in processes if p['pid'] != 0][:32]:
        row = dict(process=proc, threads=[], complete=False)
        results.append(row)
        try:
            address = int(proc['address'], 16)
            ro = pointer(address + layout['proc_ro'])
            if pointer(ro + layout['proc_owner']) != address:
                raise ValueError('process owner mismatch')
            task = pointer(ro + layout['proc_task'])
            row.update(task=hex(task), thread_count=word(task + layout['task_thread_count'], 4))
            head = task + layout['task_threads']
            thread = pointer(head)
            seen = set()
            while thread != head and thread not in seen and len(seen) < 64:
                seen.add(thread)
                tro = pointer(thread + layout['thread_ro'])
                if pointer(tro + layout['thread_owner']) != thread or pointer(tro + layout['thread_task']) != task:
                    raise ValueError('thread owner/task mismatch')
                item = dict(thread=hex(thread), thread_id=word(thread + layout['thread_id']),
                    state=word(thread + layout['thread_state'], 4),
                    continuation_raw=hex(word(thread + layout['continuation'])),
                    continuation=hex(pointer(thread + layout['continuation'])),
                    wait_event=hex(word(thread + layout['wait_event'])), kernel_frames=[])
                row['threads'].append(item)
                upcb = pointer(thread + layout['upcb'])
                if upcb:
                    state = read(upcb, 304)
                    if struct.unpack_from('<II', state) == (21, 74):
                        regs = struct.unpack_from('<33Q', state, 8)
                        item['last_user_boundary'] = dict(pc=hex(regs[32]), lr=hex(regs[30]),
                            fp=hex(regs[29]), sp=hex(regs[31]), arguments=[hex(v) for v in regs[:8]],
                            cpsr=hex(struct.unpack_from('<I', state, 272)[0]))
                base = pointer(thread + layout['kernel_stack'])
                context = pointer(thread + layout['kstackptr'])
                if base and context:
                    context += layout['context']
                    if not base <= context < base + stack_size - 112:
                        raise ValueError('saved context outside owned kernel stack')
                    fp = pointer(context + layout['saved_fp'])
                    item['saved_kernel_lr'] = hex(pointer(context + layout['saved_lr']))
                    item['saved_kernel_sp'] = hex(pointer(context + layout['saved_sp']))
                    item['kernel_stack'] = hex(base)
                    for _ in range(32):
                        if not fp:
                            break
                        if fp & 15 or not base <= fp < base + stack_size - 16:
                            item['frame_boundary'] = 'outside owned stack'
                            break
                        next_fp, lr = struct.unpack('<QQ', read(fp, 16))
                        next_fp = canonical(next_fp)
                        item['kernel_frames'].append(dict(fp=hex(fp), lr_raw=hex(lr), lr=hex(canonical(lr))))
                        if next_fp and next_fp <= fp:
                            item['frame_boundary'] = 'non-increasing chain'
                            break
                        fp = next_fp
                thread = pointer(thread + layout['thread_link'])
            row['complete'] = thread == head and len(row['threads']) == row['thread_count']
        except ValueError as error:
            row['error'] = str(error)
    return dict(read_only=True, kernel_uuid=plan['kernel_uuid'], kernel_stack_bytes=stack_size,
                process_limit=32, thread_limit=64, frame_limit=32,
                pac_metadata_stripped_for_lookup_only=True, pac_authentication_performed=False,
                boundary='saved user registers describe the latest EL0 boundary, not the current wait cause',
                kernel_frames_source='saved scheduler context; not the running thread register set',
                processes=results)
