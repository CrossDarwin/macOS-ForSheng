/* SPDX-License-Identifier: MIT */
/* 控制台可用后恢复原异常分发，不截获后续可恢复异常 */
#ifndef SHENG_EARLY_ADDRESS
#ifdef __APPLE__
#define SHENG_EARLY_ADDRESS(reg, name) adrp reg, name@page; add reg, reg, name@pageoff
#else
#define SHENG_EARLY_ADDRESS(reg, name) adrp reg, name; add reg, reg, :lo12:name
#endif
#endif
.macro SHENG_BOOTSTRAP_SYNC_SCREEN
    stp x0, x1, [sp, #-16]!
    SHENG_EARLY_ADDRESS(x0, EXT(sheng_bootstrap_capture_enabled))
    ldr w1, [x0]
    cbz w1, 1f
    ldp x0, x1, [sp], #16
    b EXT(sheng_mmu_sync_fault)
1:
    ldp x0, x1, [sp], #16
.endmacro
