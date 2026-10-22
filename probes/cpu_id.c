// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#include <errno.h>
#include <sched.h>
#include <signal.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>

static sigjmp_buf fault;
static void unsupported(int signal_number) { (void)signal_number; siglongjmp(fault, 1); }

// Linux can emulate ID reads at EL0. These values never qualify an EL2 backend.
#define READ_ID(name) do { \
    uint64_t value; \
    if (sigsetjmp(fault, 1) == 0) { \
        __asm__ volatile("mrs %0, " #name : "=r"(value)); \
        printf(",\"" #name "\":\"0x%016llx\"", (unsigned long long)value); \
    } else { printf(",\"" #name "\":null"); } \
} while (0)

int main(void)
{
    struct sigaction action = { .sa_handler = unsupported };
    sigemptyset(&action.sa_mask);
    sigaction(SIGILL, &action, NULL);
    cpu_set_t allowed;
    if (sched_getaffinity(0, sizeof(allowed), &allowed)) { perror("sched_getaffinity"); return 1; }
    puts("{\"scope\":\"linux-el0-filtered\",\"runtime_qualified\":false,\"cpus\":[");
    int first = 1;
    for (int cpu = 0; cpu < CPU_SETSIZE; ++cpu) {
        if (!CPU_ISSET(cpu, &allowed)) continue;
        cpu_set_t one;
        CPU_ZERO(&one);
        CPU_SET(cpu, &one);
        if (sched_setaffinity(0, sizeof(one), &one)) { perror("sched_setaffinity"); return 1; }
        printf("%s{\"cpu\":%d", first ? "" : ",\n", cpu);
        first = 0;
        READ_ID(midr_el1);
        READ_ID(id_aa64pfr0_el1);
        READ_ID(id_aa64pfr1_el1);
        READ_ID(id_aa64isar1_el1);
        READ_ID(id_aa64isar2_el1);
        READ_ID(id_aa64mmfr0_el1);
        READ_ID(id_aa64mmfr1_el1);
        READ_ID(id_aa64mmfr2_el1);
        READ_ID(id_aa64dfr0_el1);
        READ_ID(cntfrq_el0);
        puts("}");
    }
    puts("]}");
    return 0;
}
