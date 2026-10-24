// SPDX-License-Identifier: MIT
#ifdef __APPLE__
#define LowExceptionVectorBase _LowExceptionVectorBase
#endif
#define EXT(x) x
#define LEXT(x) x:
#define BA_VIDEO_BASE 40
#define BA_VIRT_BASE 8
#define BA_VIDEO_ROW_BYTES 56
#define BA_VIDEO_WIDTH 64
#define BA_VIDEO_HEIGHT 72
#define BA_VIDEO_DEPTH 80
#define SHENG 1
#define BOOTSTRAP_TABLE_BYTES 32768
#include "../../platform/sheng/macos26/log/bootstrap_sync.h"
#include "../../platform/sheng/macos26/log/bootstrap_trace.h"
.text
.global _start
_start:
 msr daifset, #15
 ldr x0, =test_stack_end
 mov sp, x0
 ldr x20, =boot_args
 mov x21, #0
 adr x0, LowExceptionVectorBase
 msr vbar_el1, x0
 isb
 bl Lsheng_early_enter
 .irp stage,0,1,2,3,4,5,6,7,8,9,10,11,12
 SHENG_BOOTSTRAP_TRACE \stage
 .endr
.global after_entry
after_entry:
 brk #0x123
 b .

// 关闭TTBR0后在高位地址触发异常，检查诊断路径能否恢复物理取指
.global qemu_mmu_test
qemu_mmu_test:
 mov x27, #0
 b qemu_mmu_setup
.global qemu_transition_test
qemu_transition_test:
 mov x27, #1
qemu_mmu_setup:
 mov x21, #0
 adr x0, LowExceptionVectorBase
 msr vbar_el1, x0
 isb
 SHENG_EARLY_ADDRESS x0, bootstrap_pagetables
 SHENG_EARLY_ADDRESS x1, test_l2
 orr x2, x1, #3
 str x2, [x0]
 ldr x2, =0x40000701
 str x2, [x1, #256]
 mov x25, x0
 SHENG_BOOTSTRAP_MAP_TRACE
.global qemu_trace_mapped
qemu_trace_mapped:
 SHENG_EARLY_ADDRESS x0, bootstrap_pagetables
 dsb sy
 msr ttbr0_el1, x0
 msr ttbr1_el1, x0
 ldr x0, =0x27511b511
 msr tcr_el1, x0
 mov x0, #255
 msr mair_el1, x0
 isb
 tlbi vmalle1
 dsb sy
 isb
 mrs x0, sctlr_el1
 orr x0, x0, #1
 orr x0, x0, #4
 orr x0, x0, #0x1000
 msr sctlr_el1, x0
 isb
 SHENG_BOOTSTRAP_TRACE 13
 cbnz x27, qemu_transition_setup
 adr x0, qemu_high
 ldr x1, =0xffff800000000000
 add x0, x0, x1
 br x0
qemu_transition_setup:
 // 破坏高位翻译，保留物理向量；异常栈刻意不可用
 msr ttbr1_el1, xzr
 isb
 tlbi vmalle1
 dsb sy
 isb
 mov x0, #0
 mov sp, x0
 ldr x0, =0xffff800040000000
.global qemu_transition_fault
qemu_transition_fault:
 br x0
qemu_high:
 SHENG_BOOTSTRAP_TRACE 15
 SHENG_EARLY_ADDRESS x0, test_stack_end
 mov sp, x0
 adr x0, qemu_high_vectors
 msr vbar_el1, x0
 msr ttbr0_el1, xzr
 mrs x0, tcr_el1
 orr x0, x0, #128
 msr tcr_el1, x0
 isb
 tlbi vmalle1
 dsb sy
 isb
.global qemu_high_fault
qemu_high_fault:
 brk #0x124
 b .

.balign 2048
qemu_high_vectors:
.rept 16
 b qemu_high_exception
 .balign 128
.endr
qemu_high_exception:
 SHENG_BOOTSTRAP_SYNC_SCREEN
.global qemu_normal_dispatch
qemu_normal_dispatch:
 mrs x0, elr_el1
 add x0, x0, #4
 msr elr_el1, x0
 eret
.balign 4096
.global LowExceptionVectorBase
LowExceptionVectorBase:
.rept 16
 b Lsheng_early_exception
 .balign 128
.endr
#include "../../platform/sheng/macos26/log/early_exception.h"
.org LowExceptionVectorBase+4096
.data
.balign 8
boot_args:
 .space 8
 .quad 0xffff800040200000,0x40200000
 .space 16
 .quad 0x44000000,0,2560,640,640,32
.global sheng_bootstrap_capture_enabled
sheng_bootstrap_capture_enabled:
 .word 1
.bss
.balign 16384
.global bootstrap_pagetables
bootstrap_pagetables:
 .space 16384
test_l2:
 .space 16384
.global sheng_bootstrap_fb_l2
sheng_bootstrap_fb_l2:
 .space 16384
.global sheng_bootstrap_fb_trace_ready
sheng_bootstrap_fb_trace_ready:
 .space 8
.balign 16
test_stack:
 .space 16384
test_stack_end:
