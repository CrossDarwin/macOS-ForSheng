/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Included once by the retained-log owner; no allocation or waiting in hooks. */
#include "pe_sheng_boot_progress.h"
unsigned sheng_boot_progress_enabled;
static uint32_t sheng_boot_progress_writer;
struct sheng_boot_progress sheng_boot_progress_state = { .last_service = SHENG_BOOT_SERVICES };
static uint64_t sheng_boot_progress_reported;
static uint32_t sheng_boot_progress_reported_mask;

uint64_t sheng_boot_progress_seconds(void);
#include "pe_sheng_smp_log.h"

static int sheng_boot_lock(void)
{
    uint32_t expected = 0;
    if (__atomic_compare_exchange_n(&sheng_boot_progress_writer, &expected, 1, 0,
        __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) return 1;
    __atomic_fetch_add(&sheng_boot_progress_state.events_lost, 1, __ATOMIC_RELAXED);
    return 0;
}

static void sheng_boot_unlock(void)
{
    __atomic_store_n(&sheng_boot_progress_writer, 0, __ATOMIC_RELEASE);
}

/* The unused bottom of the panic region owns four rows until a panic or GUI handoff. */
static void sheng_boot_render(char lines[4][96])
{
    if (!sheng_panel_ready || !sheng_panic_panel.base || sheng_panic_panel.rows < 6 ||
        __atomic_load_n(&sheng_panic_text_state, __ATOMIC_ACQUIRE) == 2) return;
    const unsigned scale = sheng_panic_panel.scale;
    const uintptr_t base = sheng_panic_panel.base + (sheng_panic_panel.rows - 4) *
        16 * scale * sheng_panic_panel.stride;
    for (unsigned line = 0; line < 4; line++) {
        unsigned end = 0;
        while (end < 95 && lines[line][end]) end++;
        for (unsigned y = 0; y < 16 * scale; y++) {
            uint64_t saved_daif;
            if (!sheng_fb_begin(SHENG_FB_BOOT, &saved_daif)) return;
            for (unsigned col = 0; col < sheng_panic_panel.columns; col++) {
                const unsigned char c = col < end ? (unsigned char)lines[line][col] : ' ';
                volatile uint32_t *pixels = (volatile uint32_t *)(base +
                    (line * 16 * scale + y) * sheng_panic_panel.stride + col * 8 * scale * 4);
                const unsigned bits = sheng_panel_font[c * 16 + y / scale];
                for (unsigned x = 0; x < 8 * scale; x++)
                    pixels[x] = bits & (1u << (x / scale)) ? 0xffffffffu : 0xff000000u;
            }
            sheng_fb_end(saved_daif);
        }
    }
    __asm__ volatile("dsb sy" ::: "memory");
}

static void sheng_boot_emit(const char *text)
{
    const char *prefix = "\nSHENG-PROGRESS: ";
    while (*prefix) sheng_log_putc(*prefix++);
    for (unsigned i = 0; text[i] && i < 95; i++) sheng_log_putc(text[i]);
    sheng_log_putc('\n');
}

/* Refresh ages without moving segments; emit at most one periodic summary per 30 seconds. */
void sheng_boot_progress_tick(void)
{
    sheng_smp_log_tick();
    if (!sheng_boot_progress_enabled || !sheng_boot_lock()) return;
    uint64_t now = sheng_boot_progress_seconds();
    if (now >= sheng_boot_progress_state.now) sheng_boot_progress_state.now = now;
    char lines[4][96];
    sheng_boot_format(&sheng_boot_progress_state,
        __atomic_load_n(&sheng_log_buffer.total, __ATOMIC_RELAXED),
        __atomic_load_n(&sheng_log_buffer.dropped, __ATOMIC_RELAXED), lines);
    sheng_boot_render(lines);
    int report = sheng_boot_progress_state.mask != sheng_boot_progress_reported_mask ||
        (now >= sheng_boot_progress_reported && now - sheng_boot_progress_reported >= 30);
    if (report) {
        sheng_boot_progress_reported = now;
        sheng_boot_progress_reported_mask = sheng_boot_progress_state.mask;
    }
    struct sheng_boot_progress snapshot = sheng_boot_progress_state;
    sheng_boot_unlock();
    if (report) {
        for (unsigned i = 0; i < 4; i++) sheng_boot_emit(lines[i]);
        /* A bounded inventory survives missing individual exec lines; zero starts means unobserved. */
        for (unsigned i = 0; i < SHENG_BOOT_SERVICES; i++) {
            snapshot.last_service = i;
            sheng_boot_format(&snapshot, 0, 0, lines);
            sheng_boot_emit(lines[2]);
        }
    }
}

void sheng_boot_checkpoint(unsigned stage)
{
    if (!sheng_boot_progress_enabled || !sheng_boot_lock()) return;
    int changed = sheng_boot_mark(&sheng_boot_progress_state, stage, sheng_boot_progress_seconds());
    sheng_boot_unlock();
    if (changed) sheng_boot_progress_tick();
}

void sheng_boot_service(const char *name, int pid, int exiting, int status)
{
    if (!sheng_boot_progress_enabled || !sheng_boot_lock()) return;
    int changed = sheng_boot_service_event(&sheng_boot_progress_state, name, pid,
        exiting, status, sheng_boot_progress_seconds());
    char line[96]; unsigned n = 0;
    if (changed) {
        sheng_boot_append(line, &n, exiting ? "exit " : "exec ");
        sheng_boot_append(line, &n, sheng_boot_service_names[sheng_boot_progress_state.last_service]);
        sheng_boot_append(line, &n, " pid="); sheng_boot_number(line, &n, (unsigned)pid);
        sheng_boot_append(line, &n, " wait-status="); sheng_boot_number(line, &n, (unsigned)status);
    }
    sheng_boot_unlock();
    if (changed) { sheng_boot_emit(line); sheng_boot_progress_tick(); }
}

void sheng_boot_log_state(unsigned state, unsigned error, uint64_t generation)
{
    if (!sheng_boot_progress_enabled || !sheng_boot_lock()) return;
    sheng_boot_progress_state.log_state = state;
    sheng_boot_progress_state.log_error = error;
    sheng_boot_progress_state.generation = generation;
    sheng_boot_unlock();
    sheng_boot_progress_tick();
}
