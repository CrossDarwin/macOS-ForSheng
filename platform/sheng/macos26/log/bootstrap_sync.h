/* SPDX-License-Identifier: MIT */
/* Restore normal exception dispatch once the console is ready; leave later recoverable faults untouched. */
#ifndef SHENG_EARLY_ADDRESS_DEFINED
#define SHENG_EARLY_ADDRESS_DEFINED
/* Darwin assembly treats semicolons as comments; place each instruction on its own line. */
.macro SHENG_EARLY_ADDRESS reg, name
#ifdef __APPLE__
    adrp \reg, \name@page
    add \reg, \reg, \name@pageoff
#else
    adrp \reg, \name
    add \reg, \reg, :lo12:\name
#endif
.endmacro
#endif
.macro SHENG_BOOTSTRAP_SYNC_SCREEN
    stp x0, x1, [sp, #-16]!
    SHENG_EARLY_ADDRESS x0, EXT(sheng_bootstrap_capture_enabled)
    ldr w1, [x0]
    cbz w1, 1f
    ldp x0, x1, [sp], #16
    b EXT(sheng_mmu_sync_fault)
1:
    ldp x0, x1, [sp], #16
.endmacro
