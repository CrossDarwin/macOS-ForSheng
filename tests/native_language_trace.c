// SPDX-License-Identifier: GPL-3.0-or-later
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint64_t x[29], fp, lr, sp, pc;
    uint32_t cpsr;
    bool is64;
} arm_saved_state_t;

#define TUNABLE(type, name, argument, value) type name = value
#define PSR64_IS_USER(cpsr) (((cpsr) & 15) == 0)
#define ISS_BRK_COMMENT(esr) ((esr) & 0xffff)
#define is_saved_state64(s) ((s)->is64)
#define get_saved_state_cpsr(s) ((s)->cpsr)
#define get_saved_state_pc(s) ((s)->pc)
#define get_saved_state_reg(s, r) ((s)->x[r])
#define saved_state64(s) (s)

static unsigned signed_updates, logs;
static void add_user_saved_state_pc(arm_saved_state_t *state, int step)
{
    signed_updates++;
    state->pc += step;
}

uint32_t sheng_recovery_ui_enabled;
static char process_name[32] = "Language Chooser";
void proc_selfname(char *name, int size) { snprintf(name, (size_t)size, "%s", process_name); }
int proc_selfpid(void) { return 159; }
static unsigned char *memory;
static uint64_t load_base = 0x109000000;
static int deny_copy;
static int copyin(uint64_t address, void *data, size_t size)
{
    if (deny_copy || address < load_base || size > 0x40000 || address - load_base > 0x40000 - size)
        return 1;
    memcpy(data, memory + address - load_base, size);
    return 0;
}
static int trace_printf(const char *format, ...)
{
    (void)format;
    logs++;
    return 0;
}
#define printf trace_printf
#include "../platform/sheng/macos26/recovery/language_trace_kernel.h"
#undef printf

static arm_saved_state_t state_for(unsigned index, uint64_t value)
{
    arm_saved_state_t state = {.is64 = true, .cpsr = 0xa0000000,
        .fp = 0x100, .lr = 0x101, .sp = 0x102, .pc = load_base + sheng_language_points[index].rva};
    for (unsigned i = 0; i < 29; i++) state.x[i] = 0x1000 + i;
    state.x[0] = value;
    return state;
}

static void rejected(arm_saved_state_t *state, unsigned tag)
{
    arm_saved_state_t before = *state;
    unsigned saved_logs = logs, saved_updates = signed_updates;
    assert(!sheng_language_trace(state, tag));
    assert(!memcmp(state, &before, sizeof(before)));
    assert(logs == saved_logs && signed_updates == saved_updates);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    static unsigned char bytes[0x40000];
    memory = bytes;
    FILE *input = fopen(argv[1], "rb");
    assert(input && fread(bytes, 1, sizeof(bytes), input) == sizeof(bytes));
    fclose(input);
    for (unsigned index = 0; index < 5; index++) {
        uint32_t brk = 0xd4200000 | (uint32_t)sheng_language_points[index].tag << 5;
        memcpy(bytes + sheng_language_points[index].rva, &brk, 4);
    }
    arm_saved_state_t state = state_for(2, 37);
    rejected(&state, 0x5a03);
    sheng_language_trace_enabled = 1;
    rejected(&state, 0x5a03);
    sheng_recovery_ui_enabled = 1;
    for (unsigned index = 0; index < 5; index++) {
        for (unsigned nonzero = 0; nonzero < 2; nonzero++) {
            state = state_for(index, nonzero ? 0x123456789 : 0);
            arm_saved_state_t expected = state;
            const struct sheng_language_point *point = &sheng_language_points[index];
            expected.pc += point->branch && nonzero ? 20 : 4;
            if (!point->branch) expected.x[point->destination] = state.x[0];
            assert(sheng_language_trace(&state, point->tag));
            assert(!memcmp(&state, &expected, sizeof(state)));
        }
    }
    state = state_for(2, 37);
    strcpy(process_name, "WindowServer"); rejected(&state, 0x5a03);
    strcpy(process_name, "Language Chooser");
    rejected(&state, 0xc471); // PAC failure breakpoints must reach normal exception handling.
    rejected(&state, 0x5a02);
    state.cpsr |= 5; rejected(&state, 0x5a03); state.cpsr &= ~15u;
    state.is64 = false; rejected(&state, 0x5a03); state.is64 = true;
    state.pc += 4; rejected(&state, 0x5a03); state.pc -= 4;
    deny_copy = 1; rejected(&state, 0x5a03); deny_copy = 0;
    bytes[SHENG_LANGUAGE_UUID_OFFSET + 8] ^= 1; rejected(&state, 0x5a03);
    bytes[SHENG_LANGUAGE_UUID_OFFSET + 8] ^= 1;
    bytes[sheng_language_points[2].rva] ^= 1; rejected(&state, 0x5a03);
    bytes[sheng_language_points[2].rva] ^= 1;
    unsigned before_logs = logs, before_updates = signed_updates;
    for (unsigned i = 0; i < 100; i++) {
        state = state_for(2, 37);
        assert(sheng_language_trace(&state, 0x5a03));
        assert(state.pc == load_base + sheng_language_points[2].rva + 4);
    }
    assert(logs - before_logs == 30 && signed_updates - before_updates == 100);
    puts("Language trace admission, replay, saved-state preservation and log bounds passed");
    return 0;
}
