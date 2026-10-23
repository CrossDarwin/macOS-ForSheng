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

// x0为16KiB对齐的双解释页表，x1接收四次PAR，x2为TCR基值
// 执行区必须为2GiB至64GiB的恒等映射，调用方先确认地址并清理页表缓存
.global ShengEl1GranuleProbe
ShengEl1GranuleProbe:
    save_frame
    sub sp,sp,#16
    mrs x9,pan
    str x9,[sp]
    mov x25,x0
    mov x26,x1
    mov x27,x2
    mrs x19,sctlr_el1
    mrs x20,tcr_el1
    mrs x21,ttbr0_el1
    mrs x22,mair_el1
    mrs x23,daif
    mrs x24,par_el1
    mrs x28,vbar_el1
    msr daifset,#15
    adr x9,ShengEl1ProbeVectors
    msr vbar_el1,x9
    isb
    mov x9,#1
    str x9,[x26,#56]

    // 4K有效控制，后续执行始终由表内的恒等映射覆盖
    mov x9,#0x741
    stp x9,xzr,[x25]
    dc cvac,x25
    dsb sy
    bic x9,x19,#1
    msr sctlr_el1,x9
    isb
    msr ttbr0_el1,x25
    mov x9,#0xff
    msr mair_el1,x9
    msr tcr_el1,x27
    tlbi vmalle1
    dsb sy
    isb
    bic x9,x19,#(1<<19)
    orr x9,x9,#1
    msr sctlr_el1,x9
    isb
    mov x10,#0x1000
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x26]
    mov x9,#2
    str x9,[x26,#56]

    // 空表控制仅移除低地址叶子，不移除探针执行区
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
    mov x9,#3
    str x9,[x26,#56]

    // 与Snapintosh相同的区分地址：16K索引1，4K索引0
    mov x9,#0x741
    movk x9,#0x400,lsl #16
    str x9,[x25,#8]
    dc cvac,x25
    dsb ishst
    tlbi vmalle1
    dsb ish
    isb
    mov x10,#0x1000
    movk x10,#0x200,lsl #16
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x26,#16]
    mov x9,#4
    str x9,[x26,#56]
#ifdef SHENG_GRANULE_INJECT_FAULT
    .inst 0
#endif

    bic x9,x19,#1
    dsb sy
    msr sctlr_el1,x9
    isb
#ifndef SHENG_GRANULE_FORCE_4K
    orr x9,x27,#(2<<14)
#else
    mov x9,x27
#endif
    msr tcr_el1,x9
    tlbi vmalle1
    dsb sy
    isb
    bic x9,x19,#(1<<19)
    orr x9,x9,#1
    msr sctlr_el1,x9
    isb
    at s1e1r,x10
    isb
    mrs x9,par_el1
    str x9,[x26,#24]
    mov x9,#5
    str x9,[x26,#56]
    mov x0,#0
    b .Lgranule_restore

.Lgranule_fault:
    mrs x10,esr_el1
    mrs x11,far_el1
    mrs x12,elr_el1
    mov x0,#1

    // 两种页表解释都能执行本段，所以4K回退仍能恢复固件
.Lgranule_restore:
    bic x9,x19,#1
    dsb sy
    msr sctlr_el1,x9
    isb
    msr ttbr0_el1,x21
    msr tcr_el1,x20
    msr mair_el1,x22
    tlbi vmalle1
    dsb sy
    isb
    msr sctlr_el1,x19
    isb
    cbz x0,1f
    stp x10,x11,[x26,#32]
    str x12,[x26,#48]
1:
    msr vbar_el1,x28
    msr par_el1,x24
    ldr x9,[sp]
    msr pan,x9
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
