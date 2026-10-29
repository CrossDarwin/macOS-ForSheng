// SPDX-License-Identifier: GPL-3.0-or-later
// Initialized data survives arm_init's BSS clearing and is cleaned before PSCI CPU_ON.
.data
.p2align 7
.globl EXT(sheng_boot_pac_bank)
EXT(sheng_boot_pac_bank):
    .space 80, 0
.globl EXT(sheng_boot_pac_ready)
EXT(sheng_boot_pac_ready):
    .long 0
    .long 0
.text
