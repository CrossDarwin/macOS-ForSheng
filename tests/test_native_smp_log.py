# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SmpLog(unittest.TestCase):
    def test_counter_changes_interval_and_negative_psci(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('requires a C compiler')
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            (work / 'runtime.c').write_text('''
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include "boot_progress.h"
static char output[32768];
static unsigned used;
static uint64_t now;
static void sheng_log_putc(char c) { assert(used < sizeof(output) - 1); output[used++] = c; output[used] = 0; }
static uint64_t sheng_boot_progress_seconds(void) { return now; }
volatile uint32_t armcpu_smp_running, armcpu_smp_requested;
volatile uint32_t armcpu_smp_step[8], armcpu_smp_fail[8];
volatile int32_t armcpu_smp_psci_rc[8];
volatile uint32_t armcpu_smp_mpidr[8], armcpu_smp_seen_mpidr[8];
volatile uint32_t armcpu_core_timer[8], armcpu_core_sgi[8];
volatile uint64_t armcpu_ipi_sent, armcpu_ipi_interrupts;
#include "smp_log.h"
int main(void) {
    struct sheng_boot_progress progress = { .last_service = SHENG_BOOT_SERVICES };
    char lines[4][96];
    sheng_boot_service_event(&progress, "launchd", 1, 0, 0, 0);
    uint32_t mask = progress.mask;
    sheng_smp_log_cpus = 8;
    armcpu_smp_running = 6;
    for (unsigned cpu = 0; cpu < 8; cpu++) {
        armcpu_smp_step[cpu] = cpu == 7 ? 4 : 7;
        armcpu_smp_mpidr[cpu] = cpu * 256;
        armcpu_core_timer[cpu] = 123 + cpu;
        armcpu_core_sgi[cpu] = 10 + cpu;
    }
    armcpu_smp_psci_rc[7] = INT32_MIN;
    sheng_smp_log_tick();
    sheng_boot_format(&progress, used, 0, lines);
    assert(progress.mask == mask);
    assert(strstr(output, "cpu=7 step=4 fail=0 psci=-2147483648"));
    assert(strstr(output, "cpu=7 timer=130 ipi=17"));
    assert(strstr(output, "cpu=7 requested-affinity=1792 seen-affinity=0"));
    unsigned first = used;
    now = 29; armcpu_core_timer[0]++;
    sheng_smp_log_tick(); assert(used == first);
    now = 30; sheng_smp_log_tick(); assert(used > first);
    first = used;
    now = 31; armcpu_smp_fail[7] = 4;
    sheng_smp_log_tick(); assert(used > first);
    first = used;
    sheng_smp_log_writer = 1; now = 90;
    sheng_smp_log_tick(); assert(used == first);
    sheng_smp_log_writer = 0;
    sheng_smp_log_cpus = 9;
    sheng_smp_log_tick(); assert(used == first);
}
''')
            binary = str(work / 'runtime')
            subprocess.run([compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                '-I' + str(ROOT / 'platform/sheng/macos26/log'), str(work / 'runtime.c'), '-o', binary],
                check=True, timeout=30)
            subprocess.run([binary], check=True, timeout=10)
