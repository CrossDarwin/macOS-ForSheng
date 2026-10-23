// SPDX-License-Identifier: MIT
// EL1下独立执行，临时状态期间不调用C代码或固件服务
.text
.arch_extension pan
.p2align 4

.macro save_frame
    stp x19,x20,[sp,#-96]!
    stp x21,x22,[sp,#16]
    stp x23,x24,[sp,#32]
    stp x25,x26,[sp,#48]
    stp x27,x28,[sp,#64]
    stp x29,x30,[sp,#80]
.endm
.macro restore_frame
    ldp x21,x22,[sp,#16]
    ldp x23,x24,[sp,#32]
    ldp x25,x26,[sp,#48]
    ldp x27,x28,[sp,#64]
    ldp x29,x30,[sp,#80]
    ldp x19,x20,[sp],#96
.endm

// x13为首格像素地址，x14为行跨度；只使用调用者临时寄存器
// 绿色格子在每次控制寄存器切换后直接写入显示内存
.macro mmu_mark number, color=0xff00
    cbz x13,.Lmark_done\@
    add x16,x13,#(\number * 128)
    mov x15,#12
    mov w9,#(\color & 0xffff)
    movk w9,#((\color >> 16) & 0xffff),lsl #16
.Lmark_row\@:
    add x17,x16,#96
.Lmark_pixel\@:
    stp w9,w9,[x16]
    dc cvac,x16
    add x16,x16,#8
    cmp x16,x17
    b.lo .Lmark_pixel\@
    sub x16,x16,#96
    add x16,x16,x14
    subs x15,x15,#1
    b.ne .Lmark_row\@
    dsb sy
.Lmark_done\@:
.endm

// x0为16KiB对齐的临时页表，x1接收结果，x2为保留固件TTBR0配置的TCR
// x3/x4为显示标记，x5为使用现有MAIR的叶描述符；仅操作原本禁用的TTBR1
.global ShengEl1GranuleProbe
ShengEl1GranuleProbe:
    save_frame
    mov x13,x3
    mov x14,x4
    mmu_mark 0
    sub sp,sp,#16
    mrs x9,pan
    str x9,[sp]
    mov x25,x0
    mov x26,x1
    mov x27,x2
    mov x29,x5
    mrs x19,sctlr_el1
    mrs x20,tcr_el1
    mrs x21,ttbr1_el1
    mrs x22,mair_el1
    mrs x23,daif
    mrs x24,par_el1
    mrs x28,vbar_el1
    msr daifset,#15
    adr x9,ShengEl1ProbeVectors
    msr vbar_el1,x9
    isb
    mmu_mark 1
    mov x9,#1
    str x9,[x26,#56]

    // 固件TTBR0和MAIR始终保留，临时表只被高地址AT指令访问
    stp x29,xzr,[x25]
    dc cvac,x25
    dsb ish
    msr ttbr1_el1,x25
    isb
    mmu_mark 2
    msr tcr_el1,x27
    isb
    tlbi vmalle1
    dsb ish
    isb
    mmu_mark 3
    mov x10,#0x1000
    movk x10,#0xfff0,lsl #32
    movk x10,#0xffff,lsl #48
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x26]
    mmu_mark 4
    mov x9,#2
    str x9,[x26,#56]

    str xzr,[x25]
    dc cvac,x25
    dsb ishst
    tlbi vmalle1
    dsb ish
    isb
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x26,#8]
    mmu_mark 5
    mov x9,#3
    str x9,[x26,#56]

    // 高地址低36位为0x2001000，16K索引1，4K索引0
    orr x9,x29,#0x4000000
    str x9,[x25,#8]
    dc cvac,x25
    dsb ishst
    tlbi vmalle1
    dsb ish
    isb
    movk x10,#0x200,lsl #16
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x26,#16]
    mmu_mark 6
    mov x9,#4
    str x9,[x26,#56]
#ifdef SHENG_GRANULE_INJECT_FAULT
    .inst 0
#endif

    // 先禁用并清除临时高地址翻译，再更改TG1，不改动执行区的TG0
    orr x9,x27,#(1<<23)
    msr tcr_el1,x9
    isb
    tlbi vmalle1
    dsb ish
    isb
    mmu_mark 7
    mrs x9,tcr_el1
#ifndef SHENG_GRANULE_FORCE_4K
    bic x9,x9,#(3<<30)
    orr x9,x9,#(1<<30)
#endif
    msr tcr_el1,x9
    isb
    mmu_mark 8
    mrs x9,tcr_el1
    bic x9,x9,#(1<<23)
    msr tcr_el1,x9
    isb
    tlbi vmalle1
    dsb ish
    isb
    mmu_mark 9
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x26,#24]
    mmu_mark 10
    mov x9,#5
    str x9,[x26,#56]
    mov x0,#0
    b .Lgranule_restore

.Lgranule_fault:
    mrs x10,esr_el1
    mrs x11,far_el1
    mrs x12,elr_el1
    mov x0,#1

.Lgranule_restore:
    mrs x9,tcr_el1
    orr x9,x9,#(1<<23)
    msr tcr_el1,x9
    isb
    tlbi vmalle1
    dsb ish
    isb
    mmu_mark 11
    msr ttbr1_el1,x21
    isb
    mmu_mark 12
    msr tcr_el1,x20
    isb
    tlbi vmalle1
    dsb ish
    isb
    mmu_mark 13
    cbz x0,1f
    stp x10,x11,[x26,#32]
    str x12,[x26,#48]
1:
    msr vbar_el1,x28
    msr par_el1,x24
    ldr x9,[sp]
    msr pan,x9
    mmu_mark 14
    mmu_mark 15
    msr daif,x23
    add sp,sp,#16
    restore_frame
    ret
.p2align 11
ShengEl1ProbeVectors:
.rept 16
    b .Lgranule_fault
    .balign 128
.endr
.global ShengEl1GranuleProbeEnd
ShengEl1GranuleProbeEnd:

.arch_extension pauth
.macro save_key crm,lo,hi,off
    mrs x9,s3_0_c2_c\crm\()_\lo
    mrs x10,s3_0_c2_c\crm\()_\hi
    stp x9,x10,[sp,#\off]
.endm
.macro load_key crm,lo,hi,off
    ldp x9,x10,[sp,#\off]
    msr s3_0_c2_c\crm\()_\lo,x9
    msr s3_0_c2_c\crm\()_\hi,x10
.endm
.macro compare_key crm,lo,hi,off
    ldp x9,x10,[sp,#\off]
    mrs x11,s3_0_c2_c\crm\()_\lo
    eor x9,x9,x11
    mrs x11,s3_0_c2_c\crm\()_\hi
    eor x10,x10,x11
    orr x12,x12,x9
    orr x12,x12,x10
.endm
.macro install_keys seed
    mov x9,#\seed
    add x10,x9,#1
    msr apiakeylo_el1,x9
    msr apiakeyhi_el1,x10
    add x9,x9,#2
    add x10,x10,#2
    msr apibkeylo_el1,x9
    msr apibkeyhi_el1,x10
    add x9,x9,#2
    add x10,x10,#2
    msr apdakeylo_el1,x9
    msr apdakeyhi_el1,x10
    add x9,x9,#2
    add x10,x10,#2
    msr apdbkeylo_el1,x9
    msr apdbkeyhi_el1,x10
    add x9,x9,#2
    add x10,x10,#2
    msr apgakeylo_el1,x9
    msr apgakeyhi_el1,x10
    isb
.endm
.macro address_roundtrip sign,auth,off,bit
    mov x9,x20
    \sign x9,x21
    str x9,[x19,#\off]
    \auth x9,x21
    cmp x9,x20
    cset x10,eq
    orr x22,x22,x10,lsl #\bit
.endm

// 结果为五类密钥A/B签名，返回0x7fff表示区分、认证与固件状态恢复均通过
// 原始密钥只暂存在本核栈内，恢复后清除，不进入输出记录
.global ShengEl1PauthProbe
ShengEl1PauthProbe:
    save_frame
    sub sp,sp,#96
    mov x19,x0
    adr x20,ShengEl1PauthProbe
    mov x21,#0x1234
    mov x22,#0
    mrs x23,sctlr_el1
    mrs x24,daif
    msr daifset,#15
    save_key 1,0,1,0
    save_key 1,2,3,16
    save_key 2,0,1,32
    save_key 2,2,3,48
    save_key 3,0,1,64
    install_keys 0x1100
    mov x9,#0x2000
    movk x9,#0xc800,lsl #16
    orr x9,x23,x9
    msr sctlr_el1,x9
    isb
    address_roundtrip pacia,autia,0,5
    address_roundtrip pacib,autib,8,6
    address_roundtrip pacda,autda,16,7
    address_roundtrip pacdb,autdb,24,8
    pacga x9,x20,x21
    str x9,[x19,#32]
    install_keys 0x3300
    address_roundtrip pacia,autia,40,9
    address_roundtrip pacib,autib,48,10
    address_roundtrip pacda,autda,56,11
    address_roundtrip pacdb,autdb,64,12
    pacga x9,x20,x21
    str x9,[x19,#72]
    mov x11,#0
1:
    ldr x9,[x19,x11]
    add x12,x11,#40
    ldr x10,[x19,x12]
    cmp x9,x10
    cset x10,ne
    lsr x12,x11,#3
    lsl x10,x10,x12
    orr x22,x22,x10
    add x11,x11,#8
    cmp x11,#40
    b.ne 1b
    install_keys 0x1100
    pacga x9,x20,x21
    ldr x10,[x19,#32]
    cmp x9,x10
    cset x10,eq
    orr x22,x22,x10,lsl #13
    load_key 1,0,1,0
    load_key 1,2,3,16
    load_key 2,0,1,32
    load_key 2,2,3,48
    load_key 3,0,1,64
    msr sctlr_el1,x23
    isb
    mov x12,#0
    compare_key 1,0,1,0
    compare_key 1,2,3,16
    compare_key 2,0,1,32
    compare_key 2,2,3,48
    compare_key 3,0,1,64
    mrs x9,sctlr_el1
    eor x9,x9,x23
    orr x12,x12,x9
    cmp x12,#0
    cset x10,eq
    orr x22,x22,x10,lsl #14
    stp xzr,xzr,[sp]
    stp xzr,xzr,[sp,#16]
    stp xzr,xzr,[sp,#32]
    stp xzr,xzr,[sp,#48]
    stp xzr,xzr,[sp,#64]
    mov x0,x22
    msr daif,x24
    add sp,sp,#96
    restore_frame
    ret
