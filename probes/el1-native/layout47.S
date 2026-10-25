// SPDX-License-Identifier: MIT
#include "layout47.h"
.text
.arch_extension pan
.p2align 4
.global ShengEl1Layout47Probe
ShengEl1Layout47Probe:
    stp x19,x20,[sp,#-96]!
    stp x21,x22,[sp,#16]
    stp x23,x24,[sp,#32]
    stp x25,x26,[sp,#48]
    stp x27,x28,[sp,#64]
    stp x29,x30,[sp,#80]
    mov x19,x1
    mov x25,x0
    mov x26,x2
    mov x13,x3
    mov x14,x4
    mov x27,#0
    mrs x20,tcr_el1
    mrs x21,ttbr1_el1
    mrs x22,vbar_el1
    mrs x23,daif
    mrs x24,par_el1
    mrs x29,pan
    msr daifset,#15
    adr x9,ShengLayout47Vectors
    msr vbar_el1,x9
    isb
    mov x9,#1
    str x9,[x19,#104]
    // Markers use only x9 and x13-x17; the temporary window must not overlap the firmware display mapping.
    mov x28,#0
    bl .Lmark47
    mov x28,#1
    bl .Lmark47
    msr ttbr1_el1,x25
    isb
    mov x28,#2
    bl .Lmark47
    msr tcr_el1,x26
    isb
    tlbi vmalle1
    dsb ish
    ic iallu
    dsb ish
    isb
    mov x28,#3
    bl .Lmark47
    ldr x10,=SHENG47_LOW
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x19]
    mov x28,#4
    bl .Lmark47
    ldr x10,=SHENG47_CODE
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x19,#8]
    mov x28,#5
    bl .Lmark47
    ldr x10,=SHENG47_DATA
    at s1e1w,x10
    isb
    mrs x9,par_el1
    str x9,[x19,#16]
    mov x28,#6
    bl .Lmark47
    ldr x10,=SHENG47_CODE
    at s1e1w,x10
    isb
    mrs x9,par_el1
    str x9,[x19,#24]
    mov x28,#7
    bl .Lmark47
    mov x9,#2
    str x9,[x19,#104]
#ifdef SHENG_LAYOUT47_INJECT_FAULT
    .inst 0
#endif
    ldr x16,=SHENG47_LOW
    ldr x1,=SHENG47_DATA
    mov x2,#0x4747
    blr x16
    str x0,[x19,#32]
    str x2,[x19,#48]
    mov x28,#8
    bl .Lmark47
    mov x9,#3
    str x9,[x19,#104]
    ldr x16,=SHENG47_CODE
    ldr x1,=SHENG47_DATA
    mov x2,#0x5757
    blr x16
    str x0,[x19,#40]
    str x2,[x19,#56]
    mov x28,#9
    bl .Lmark47
    ldr x1,=SHENG47_DATA
    ldr x9,[x1]
    str x9,[x19,#64]
    mov x28,#10
    bl .Lmark47
    ldr x10,=SHENG47_HOLE
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x19,#72]
    mov x28,#11
    bl .Lmark47
    b .Lrestore47
.Lfault47:
    mrs x9,esr_el1
    str x9,[x19,#80]
    mrs x9,far_el1
    str x9,[x19,#88]
    mrs x9,elr_el1
    str x9,[x19,#96]
    mov x27,#1
.Lrestore47:
    mrs x9,tcr_el1
    orr x9,x9,#(1<<23)
    msr tcr_el1,x9
    isb
    tlbi vmalle1
    dsb ish
    isb
    mov x28,#12
    bl .Lmark47
    msr ttbr1_el1,x21
    isb
    msr tcr_el1,x20
    isb
    tlbi vmalle1
    dsb ish
    isb
    mov x28,#13
    bl .Lmark47
    msr vbar_el1,x22
    msr par_el1,x24
    msr pan,x29
    mov x28,#14
    bl .Lmark47
    mov x28,#15
    bl .Lmark47
    mov x0,x27
    msr daif,x23
    ldp x21,x22,[sp,#16]
    ldp x23,x24,[sp,#32]
    ldp x25,x26,[sp,#48]
    ldp x27,x28,[sp,#64]
    ldp x29,x30,[sp,#80]
    ldp x19,x20,[sp],#96
    ret
.Lmark47:
    cbz x13,3f
    add x16,x13,x28,lsl #7
    mov x15,#12
    mov w9,#0xff00
1:  add x17,x16,#96
2:  stp w9,w9,[x16]
    dc cvac,x16
    add x16,x16,#8
    cmp x16,x17
    b.lo 2b
    sub x16,x16,#96
    add x16,x16,x14
    subs x15,x15,#1
    b.ne 1b
    dsb sy
3:  ret
.p2align 11
ShengLayout47Vectors:
.rept 16
    b .Lfault47
    .balign 128
.endr
.global ShengEl1Layout47End
ShengEl1Layout47End:

// Copy to an owned RX page and call through a 47-bit high address without original-location or firmware dependencies.
.p2align 4
.global ShengEl1Layout47Code
ShengEl1Layout47Code:
    .inst 0xd503245f // BTI c
    adr x0,ShengEl1Layout47Code
    str x2,[x1]
    ldr x2,[x1]
    ret
.global ShengEl1Layout47CodeEnd
ShengEl1Layout47CodeEnd:
