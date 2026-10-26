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
    return 0;
}
