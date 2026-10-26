/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SHENG_BOOT_PROGRESS_H
#define SHENG_BOOT_PROGRESS_H
#include <stdint.h>
#include <stddef.h>

#define SHENG_BOOT_STAGES 10u
#define SHENG_BOOT_SERVICES 10u
struct sheng_boot_service {
    uint32_t starts, exits;
    int pid, status, running;
};
struct sheng_boot_progress {
    uint32_t mask, stage, last_service, log_state, log_error;
    uint64_t now, changed, service_changed, generation, events_lost;
    struct sheng_boot_service service[SHENG_BOOT_SERVICES];
};

static const char *const sheng_boot_stage_names[SHENG_BOOT_STAGES] = {
    "Kernel", "VM ready", "IOKit entry", "Root mounted", "launchd exec",
    "Recovery exec", "WindowServer exec", "Display on", "First swap", "First frame"
};
static const char *const sheng_boot_service_names[SHENG_BOOT_SERVICES] = {
    "launchd", "recoveryosd", "RecoveryOS Agent", "WindowServer", "Language Chooser",
    "Recovery Springb", "lsd", "coreservicesd", "loginwindow", "diskarbitrationd"
};

static int sheng_boot_service_index(const char *name)
{
    if (!name) return -1;
    for (unsigned i = 0; i < SHENG_BOOT_SERVICES; i++) {
        unsigned n = 0;
        while (n < 16 && name[n] && name[n] == sheng_boot_service_names[i][n]) n++;
        if (n <= 16 && !name[n] && !sheng_boot_service_names[i][n]) return (int)i;
    }
    return -1;
}

/* A repeated milestone never refreshes the last-progress timestamp. */
static int sheng_boot_mark(struct sheng_boot_progress *state, unsigned stage, uint64_t now)
{
    if (stage >= SHENG_BOOT_STAGES || now < state->now) return 0;
    state->now = now;
    const uint32_t bit = 1u << stage;
    if (state->mask & bit) return 0;
    state->mask |= bit;
    if (stage > state->stage) state->stage = stage;
    state->changed = now;
    return 1;
}

static int sheng_boot_service_event(struct sheng_boot_progress *state, const char *name,
    int pid, int exiting, int status, uint64_t now)
{
    const int index = sheng_boot_service_index(name);
    if (index < 0 || pid <= 0 || now < state->now) return 0;
    struct sheng_boot_service *service = &state->service[index];
    if (exiting) {
        /* Ignore duplicate exits and an old PID after its replacement started. */
        if (service->pid != pid || !service->running) return 0;
        if (service->exits != UINT32_MAX) service->exits++;
        service->status = status;
        service->running = 0;
    } else {
        if (service->pid == pid && service->running) return 0;
        if (service->starts != UINT32_MAX) service->starts++;
        service->pid = pid;
        service->status = 0;
        service->running = 1;
        unsigned stage = SHENG_BOOT_STAGES;
        if (index == 0) stage = 4;
        if (index == 1 || index == 2) stage = 5;
        if (index == 3) stage = 6;
        sheng_boot_mark(state, stage, now);
        /* New services are progress; repeated starts retain the original age. */
        if (service->starts == 1) state->changed = now;
    }
    state->now = now;
    state->last_service = (unsigned)index;
    state->service_changed = now;
    return 1;
}

static void sheng_boot_append(char *out, unsigned *used, const char *text)
{
    while (*text && *used < 95) out[(*used)++] = *text++;
    out[*used] = 0;
}

static void sheng_boot_number(char *out, unsigned *used, uint64_t value)
{
    char digits[20];
    unsigned count = 0;
    do { digits[count++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (count && *used < 95) out[(*used)++] = digits[--count];
    out[*used] = 0;
}

/* Segments describe individual observed milestones, not elapsed time or percent. */
static void sheng_boot_format(const struct sheng_boot_progress *state, uint64_t bytes,
    uint64_t dropped, char lines[4][96])
{
    unsigned n = 0;
    sheng_boot_append(lines[0], &n, "BOOT [");
    for (unsigned i = 0; i < SHENG_BOOT_STAGES; i++)
        sheng_boot_append(lines[0], &n, state->mask & (1u << i) ? "#" : "-");
    sheng_boot_append(lines[0], &n, "] - ");
    sheng_boot_append(lines[0], &n, sheng_boot_stage_names[state->stage < SHENG_BOOT_STAGES ? state->stage : 0]);
    n = 0;
    sheng_boot_append(lines[1], &n, "No new stage/service: ");
    sheng_boot_number(lines[1], &n, state->now >= state->changed ? state->now - state->changed : 0);
    sheng_boot_append(lines[1], &n, "s - no loop verdict");
    n = 0;
    if (state->last_service < SHENG_BOOT_SERVICES) {
        const struct sheng_boot_service *service = &state->service[state->last_service];
        sheng_boot_append(lines[2], &n, sheng_boot_service_names[state->last_service]);
        sheng_boot_append(lines[2], &n, " pid="); sheng_boot_number(lines[2], &n, (unsigned)service->pid);
        sheng_boot_append(lines[2], &n, " starts="); sheng_boot_number(lines[2], &n, service->starts);
        sheng_boot_append(lines[2], &n, " exits="); sheng_boot_number(lines[2], &n, service->exits);
        sheng_boot_append(lines[2], &n, " wait-status="); sheng_boot_number(lines[2], &n, (unsigned)service->status);
    } else sheng_boot_append(lines[2], &n, "Services: no tracked exec yet");
    n = 0;
    const char *log_status = state->log_state == 0 ? "off" : state->log_state == 1 ? "opening" :
        state->log_state == 2 ? "verified" : state->log_state == 3 ? "committed" :
        state->log_state == 5 ? "stopped" : "unknown";
    sheng_boot_append(lines[3], &n, "LOG "); sheng_boot_append(lines[3], &n, log_status);
    sheng_boot_append(lines[3], &n, " gen="); sheng_boot_number(lines[3], &n, state->generation);
    sheng_boot_append(lines[3], &n, " bytes="); sheng_boot_number(lines[3], &n, bytes);
    sheng_boot_append(lines[3], &n, " drops="); sheng_boot_number(lines[3], &n, dropped);
    sheng_boot_append(lines[3], &n, " error="); sheng_boot_number(lines[3], &n, state->log_error);
    sheng_boot_append(lines[3], &n, " lost=");
    sheng_boot_number(lines[3], &n, __atomic_load_n(&state->events_lost, __ATOMIC_RELAXED));
}
#endif
