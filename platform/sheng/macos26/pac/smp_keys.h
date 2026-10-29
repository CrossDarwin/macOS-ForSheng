// SPDX-License-Identifier: GPL-3.0-or-later
// common_start uses physical addresses here, before enabling translation or calling C.
.macro SHENG_BOOTSTRAP_KERNEL_KEYS
#ifdef __APPLE__
    adrp x0, EXT(sheng_boot_pac_bank)@page
    add x0, x0, EXT(sheng_boot_pac_bank)@pageoff
#else
    adrp x0, EXT(sheng_boot_pac_bank)
    add x0, x0, :lo12:EXT(sheng_boot_pac_bank)
#endif
    cbnz x21, Lsheng_secondary_keys_\@
    mrs x1, APIAKeyLo_EL1
    str x1, [x0, #0]
    mrs x1, APIAKeyHi_EL1
    str x1, [x0, #8]
    mrs x1, APIBKeyLo_EL1
    str x1, [x0, #16]
    mrs x1, APIBKeyHi_EL1
    str x1, [x0, #24]
    mrs x1, APDAKeyLo_EL1
    str x1, [x0, #32]
    mrs x1, APDAKeyHi_EL1
    str x1, [x0, #40]
    mrs x1, APDBKeyLo_EL1
    str x1, [x0, #48]
    mrs x1, APDBKeyHi_EL1
    str x1, [x0, #56]
    mrs x1, APGAKeyLo_EL1
    str x1, [x0, #64]
    mrs x1, APGAKeyHi_EL1
    str x1, [x0, #72]
    add x2, x0, #80
    mov w1, #1
    stlr w1, [x2]
    b Lsheng_keys_ready_\@
Lsheng_secondary_keys_\@:
    add x2, x0, #80
    ldar w1, [x2]
    cmp w1, #1
    b.ne Lsheng_keys_unpublished_\@
    ldr x1, [x0, #0]
    msr APIAKeyLo_EL1, x1
    ldr x1, [x0, #8]
    msr APIAKeyHi_EL1, x1
    ldr x1, [x0, #16]
    msr APIBKeyLo_EL1, x1
    ldr x1, [x0, #24]
    msr APIBKeyHi_EL1, x1
    ldr x1, [x0, #32]
    msr APDAKeyLo_EL1, x1
    ldr x1, [x0, #40]
    msr APDAKeyHi_EL1, x1
    ldr x1, [x0, #48]
    msr APDBKeyLo_EL1, x1
    ldr x1, [x0, #56]
    msr APDBKeyHi_EL1, x1
    ldr x1, [x0, #64]
    msr APGAKeyLo_EL1, x1
    ldr x1, [x0, #72]
    msr APGAKeyHi_EL1, x1
    isb
    b Lsheng_keys_ready_\@
Lsheng_keys_unpublished_\@:
    brk #0x534a
    b Lsheng_keys_unpublished_\@
Lsheng_keys_ready_\@:
.endmacro
