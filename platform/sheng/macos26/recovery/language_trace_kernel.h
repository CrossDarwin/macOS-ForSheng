// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <vm/sheng_recovery_ui.h>
#include <vm/sheng_language_trace.h>
#include <vm/sheng_language_trace_pages.h>

extern void proc_selfname(char *, int);
extern int proc_selfpid(void);
extern uint32_t sheng_recovery_ui_enabled;
TUNABLE(uint32_t, sheng_language_trace_enabled, "sheng-language-trace", 0);

static bool
sheng_language_trace(arm_saved_state_t *state, uint64_t esr)
{
    if (sheng_language_trace_enabled != 1 || sheng_recovery_ui_enabled != 1 ||
        !is_saved_state64(state) || !PSR64_IS_USER(get_saved_state_cpsr(state)))
        return false;
    uint16_t tag = ISS_BRK_COMMENT(esr);
    const size_t count = sizeof(sheng_language_points) / sizeof(sheng_language_points[0]);
    if (tag < 0x5a01 || tag >= 0x5a01 + count)
        return false;
    const struct sheng_language_point *point = &sheng_language_points[tag - 0x5a01];
    uint64_t pc = get_saved_state_pc(state);
    if (pc < 0x100000000ULL + point->rva || ((pc - point->rva) & 0x3fff))
        return false;
    char name[32] = {0};
    proc_selfname(name, sizeof(name));
    if (strcmp(name, "Language Chooser"))
        return false;
    uint32_t instruction = 0;
    uint8_t identity[sizeof(sheng_language_uuid_command)];
    if (copyin(pc, &instruction, sizeof(instruction)) ||
        instruction != (0xd4200000u | (uint32_t)tag << 5) ||
        copyin(pc - point->rva + SHENG_LANGUAGE_UUID_OFFSET, identity, sizeof(identity)) ||
        memcmp(identity, sheng_language_uuid_command, sizeof(identity)))
        return false;
    uint64_t value = get_saved_state_reg(state, 0);
    int step = sheng_language_step(point, value);
    if (!step)
        return false;
    // Bound console traffic while continuing to replay every matching instruction.
    static uint32_t samples[sizeof(sheng_language_points) / sizeof(sheng_language_points[0])];
    uint32_t sample = __atomic_add_fetch(&samples[tag - 0x5a01], 1, __ATOMIC_RELAXED);
    if (sample <= 32)
        printf("SHENG-LANGUAGE: %s pid=%d sample=%u value=%llu\n", point->name,
            proc_selfpid(), sample, (unsigned long long)(point->branch || point->tag == 0x5a03 ? value : !!value));
    // X19/X20/X24 are outside XNU's signed PC/LR/CPSR/X16/X17 tuple.
    if (!point->branch)
        saved_state64(state)->x[point->destination] = value;
    // Use XNU's user-state signing helper; retain flags, SP, LR and all other registers.
    add_user_saved_state_pc(state, step);
    return true;
}
