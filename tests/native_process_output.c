/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MAXCOMLEN 16
typedef uintptr_t user_addr_t;
typedef uint64_t user_size_t;
struct proc { char p_comm[MAXCOMLEN + 1]; int pid; };
typedef struct test_uio { unsigned count; struct { user_addr_t address; user_size_t bytes; } vector[32]; } *uio_t;
static int uio_iovcnt(uio_t uio) { return (int)uio->count; }
static int uio_getiov(uio_t uio, int index, user_addr_t *address, user_size_t *bytes)
{
    *address = uio->vector[index].address; *bytes = uio->vector[index].bytes;
    return 0;
}
static char output[1024];
static size_t copied;
static int copy_error, copies;
static int proc_getpid(struct proc *process) { return process->pid; }
static int copyin(user_addr_t address, void *destination, size_t bytes)
{
    copies++;
    copied = bytes;
    if (copy_error) return copy_error;
    memcpy(destination, (const void *)address, bytes);
    return 0;
}
static void diagnostic_printf(const char *format, ...)
{
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(output, sizeof(output), format, arguments);
    va_end(arguments);
}
#define printf diagnostic_printf
#include "../platform/sheng/macos26/log/process_output.h"
#undef printf

static void reset(void) { output[0] = 0; copied = 0; copies = 0; copy_error = 0; }

int main(void)
{
    struct proc process = {"WindowServer", 90};
    const char text[] = {'a', '\n', 0, '\t', 127, '%', 's'};
    for (unsigned mode = 0; mode < 4; mode++) {
        for (int fd = 0; fd < 4; fd++) {
            reset();
            sheng_process_output(&process, fd, (uintptr_t)text, sizeof(text), mode, "");
            int enabled = (mode == 1 && fd == 2) || (mode == 2 && (fd == 1 || fd == 2));
            assert(copies == enabled);
            assert((output[0] != 0) == enabled);
            if (enabled) assert(strcmp(output, "SHENG: fd2 pid 90 WindowServer - a    %s\n") == 0 ||
                                strcmp(output, "SHENG: fd1 pid 90 WindowServer - a    %s\n") == 0);
        }
    }
    reset();
    sheng_process_output(&process, 2, 0, 0, 1, "WindowServer");
    sheng_process_output(&process, 2, 0, 100, 1, "Window");
    assert(!copies && !output[0]);
    reset(); copy_error = 14;
    sheng_process_output(&process, 2, 0, 10, 1, "WindowServer");
    assert(copies == 1 && !output[0]);
    reset();
    char long_text[159]; memset(long_text, 'X', sizeof(long_text));
    sheng_process_output(&process, 2, (uintptr_t)long_text, UINT64_MAX, 1, "WindowServer");
    assert(copied == sizeof(long_text));
    assert(strstr(output, " [truncated]\n"));
    reset();
    sheng_process_output(&process, 2, (uintptr_t)long_text, sizeof(long_text), 1, "WindowServer");
    assert(!strstr(output, "[truncated]"));
    assert(copied == sizeof(long_text));
    reset();
    struct test_uio vectors = {
        .count = 2, .vector = {{(uintptr_t)"first ", 6}, {(uintptr_t)"second", 6}}
    };
    sheng_process_outputv(&process, 2, (uio_t)(void *)&vectors, 1, "WindowServer");
    assert(copies == 2 && !strcmp(output, "SHENG: fd2 pid 90 WindowServer - first second\n"));
    reset(); copy_error = 14;
    sheng_process_outputv(&process, 2, (uio_t)(void *)&vectors, 1, "WindowServer");
    assert(copies == 1 && !output[0]);
    reset();
    vectors.vector[0].address = (uintptr_t)long_text; vectors.vector[0].bytes = sizeof(long_text);
    sheng_process_outputv(&process, 2, (uio_t)(void *)&vectors, 1, "WindowServer");
    assert(copies == 1 && copied == 159 && strstr(output, "[truncated]"));
    reset();
    vectors.count = 32;
    for (unsigned i = 0; i < 32; i++) {
        vectors.vector[i].address = (uintptr_t)"x"; vectors.vector[i].bytes = 1;
    }
    sheng_process_outputv(&process, 2, (uio_t)(void *)&vectors, 1, "WindowServer");
    assert(copies == 16 && strstr(output, "[truncated]"));
    const char *const names[] = {"recoveryosd", "RecoveryOS Agent", "Language Chooser", "Recovery Springb",
                                "WindowServer", "recoveryosdExtra", "launchd"};
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        strcpy(process.p_comm, names[i]);
        for (unsigned mode = 0; mode < 4; mode++) for (int fd = 0; fd < 4; fd++) {
            reset();
            sheng_process_output(&process, fd, (uintptr_t)text, sizeof(text), mode, "recovery-ui");
            int enabled = i < 4 && ((mode == 1 && fd == 2) || (mode == 2 && (fd == 1 || fd == 2)));
            assert(copies == enabled && (output[0] != 0) == enabled);
        }
    }
    return 0;
}
