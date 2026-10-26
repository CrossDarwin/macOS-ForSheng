/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SHENG_PROCESS_OUTPUT_H
#define SHENG_PROCESS_OUTPUT_H

/* Adapted from DroidVM ba207d7's bounded stdout/stderr diagnostic.
 * Records attempted output; a concurrent writer can change the user buffer.
 * The original write still owns its validation, side effects and return value.
 */
static void
sheng_process_output(struct proc *process, int fd, user_addr_t address,
    user_size_t bytes, unsigned mode, const char *name)
{
    if (!mode || mode > 2 || (fd != 2 && (mode != 2 || fd != 1)) || !bytes ||
        (name[0] && strncmp(process->p_comm, name, MAXCOMLEN + 1)))
        return;
    char text[160];
    size_t count = bytes < sizeof(text) - 1 ? (size_t)bytes : sizeof(text) - 1;
    if (copyin(address, text, count) != 0)
        return;
    for (size_t i = 0; i < count; i++)
        if ((unsigned char)text[i] < 32 || text[i] == 127)
            text[i] = ' ';
    text[count] = 0;
    printf("SHENG: fd%d pid %d %s - %s%s\n", fd, proc_getpid(process),
        process->p_comm, text, bytes > count ? " [truncated]" : "");
}

#endif
