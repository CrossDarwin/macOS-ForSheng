// SPDX-License-Identifier: MIT
.text
.global _start
_start:
    ldr x0,=qemu_stack_end
    mov sp,x0
    bl qemu_main
1:  wfe
    b 1b
.bss
.p2align 14
qemu_stack:
    .skip 16384
qemu_stack_end:
