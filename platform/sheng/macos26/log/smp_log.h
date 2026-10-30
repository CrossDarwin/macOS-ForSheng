/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Included by the retained-log owner after the bounded progress formatter. */
extern volatile uint32_t armcpu_smp_running, armcpu_smp_requested;
extern volatile uint32_t armcpu_smp_step[8], armcpu_smp_fail[8];
extern volatile int32_t armcpu_smp_psci_rc[8];
extern volatile uint32_t armcpu_smp_mpidr[8], armcpu_smp_seen_mpidr[8];
extern volatile uint32_t armcpu_core_timer[8], armcpu_core_sgi[8];
extern volatile uint64_t armcpu_ipi_sent, armcpu_ipi_interrupts;
unsigned sheng_smp_log_cpus;
static uint32_t sheng_smp_log_writer;
static uint64_t sheng_smp_log_reported;
static uint32_t sheng_smp_log_valid, sheng_smp_log_previous[8][3];

static void sheng_smp_field(char *line, unsigned *n, const char *name, uint64_t value)
{
    sheng_boot_append(line, n, name);
    sheng_boot_number(line, n, value);
}

static void sheng_smp_emit(const char *line)
{
    const char *prefix = "\nSHENG-SMP: ";
    while (*prefix) sheng_log_putc(*prefix++);
    for (unsigned n = 0; line[n] && n < 95; n++) sheng_log_putc(line[n]);
    sheng_log_putc('\n');
}

static void sheng_smp_log_tick(void)
{
    if (sheng_smp_log_cpus < 2 || sheng_smp_log_cpus > 8) return;
    uint32_t expected = 0;
    if (!__atomic_compare_exchange_n(&sheng_smp_log_writer, &expected, 1, 0,
        __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) return;
    uint64_t now = sheng_boot_progress_seconds();
    uint32_t state[8][3];
    int changed = !sheng_smp_log_valid;
    for (unsigned cpu = 0; cpu < sheng_smp_log_cpus; cpu++) {
        state[cpu][0] = __atomic_load_n(&armcpu_smp_step[cpu], __ATOMIC_RELAXED);
        state[cpu][1] = __atomic_load_n(&armcpu_smp_fail[cpu], __ATOMIC_RELAXED);
        state[cpu][2] = (uint32_t)__atomic_load_n(&armcpu_smp_psci_rc[cpu], __ATOMIC_RELAXED);
        for (unsigned i = 0; i < 3; i++) changed |= state[cpu][i] != sheng_smp_log_previous[cpu][i];
    }
    if (!changed && (now < sheng_smp_log_reported || now - sheng_smp_log_reported < 30)) {
        __atomic_store_n(&sheng_smp_log_writer, 0, __ATOMIC_RELEASE);
        return;
    }
    sheng_smp_log_valid = 1;
    sheng_smp_log_reported = now;
    char line[96]; unsigned n = 0;
    sheng_smp_field(line, &n, "elapsed=", now);
    sheng_smp_field(line, &n, " cpus=", sheng_smp_log_cpus);
    sheng_smp_field(line, &n, " secondaries=", __atomic_load_n(&armcpu_smp_running, __ATOMIC_RELAXED));
    sheng_smp_field(line, &n, " enabled=", __atomic_load_n(&armcpu_smp_requested, __ATOMIC_RELAXED));
    sheng_smp_emit(line);
    n = 0;
    sheng_smp_field(line, &n, "ipi-sent=", __atomic_load_n(&armcpu_ipi_sent, __ATOMIC_RELAXED));
    sheng_smp_field(line, &n, " ipi-received=", __atomic_load_n(&armcpu_ipi_interrupts, __ATOMIC_RELAXED));
    sheng_smp_emit(line);
    /* Each field is an aligned atomic sample, not a simultaneous system-wide snapshot. */
    for (unsigned cpu = 0; cpu < sheng_smp_log_cpus; cpu++) {
        n = 0;
        sheng_smp_field(line, &n, "cpu=", cpu);
        sheng_smp_field(line, &n, " step=", state[cpu][0]);
        sheng_smp_field(line, &n, " fail=", state[cpu][1]);
        sheng_boot_append(line, &n, " psci=");
        int64_t psci = (int32_t)state[cpu][2];
        if (psci < 0) sheng_boot_append(line, &n, "-");
        sheng_boot_number(line, &n, (uint64_t)(psci < 0 ? -psci : psci));
        sheng_smp_emit(line);
        n = 0;
        sheng_smp_field(line, &n, "cpu=", cpu);
        sheng_smp_field(line, &n, " requested-affinity=", __atomic_load_n(&armcpu_smp_mpidr[cpu], __ATOMIC_RELAXED));
        sheng_smp_field(line, &n, " seen-affinity=", __atomic_load_n(&armcpu_smp_seen_mpidr[cpu], __ATOMIC_RELAXED));
        sheng_smp_emit(line);
        n = 0;
        sheng_smp_field(line, &n, "cpu=", cpu);
        sheng_smp_field(line, &n, " timer=", __atomic_load_n(&armcpu_core_timer[cpu], __ATOMIC_RELAXED));
        sheng_smp_field(line, &n, " ipi=", __atomic_load_n(&armcpu_core_sgi[cpu], __ATOMIC_RELAXED));
        sheng_smp_emit(line);
        for (unsigned i = 0; i < 3; i++) sheng_smp_log_previous[cpu][i] = state[cpu][i];
    }
    __atomic_store_n(&sheng_smp_log_writer, 0, __ATOMIC_RELEASE);
}
