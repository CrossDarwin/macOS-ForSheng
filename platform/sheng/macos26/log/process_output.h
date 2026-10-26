/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef SHENG_PROCESS_OUTPUT_H
#define SHENG_PROCESS_OUTPUT_H

/* Adapted from DroidVM ba207d7's bounded stdout/stderr diagnostic.
 * Records attempted output; a concurrent writer can change the user buffer.
 * The original write still owns its validation, side effects and return value.
 */
static int sheng_process_output_enabled(struct proc *process, int fd, unsigned mode, const char *name)
{
    return mode && mode <= 2 && (fd == 2 || (mode == 2 && fd == 1)) &&
        (!name[0] || !strncmp(process->p_comm, name, MAXCOMLEN + 1));
}

static void sheng_process_output_text(struct proc *process, int fd, char text[160], size_t count, int truncated)
{
    for (size_t i = 0; i < count; i++)
        if ((unsigned char)text[i] < 32 || text[i] == 127)
            text[i] = ' ';
    text[count] = 0;
    printf("SHENG: fd%d pid %d %s - %s%s\n", fd, proc_getpid(process),
        process->p_comm, text, truncated ? " [truncated]" : "");
}

static void
sheng_process_output(struct proc *process, int fd, user_addr_t address,
    user_size_t bytes, unsigned mode, const char *name)
{
    if (!bytes || !sheng_process_output_enabled(process, fd, mode, name)) return;
    char text[160];
    size_t count = bytes < sizeof(text) - 1 ? (size_t)bytes : sizeof(text) - 1;
    if (copyin(address, text, count) != 0) return;
    sheng_process_output_text(process, fd, text, count, bytes > count);
}

/* Inspect the validated UIO without advancing it; cap the entire vector write. */
static void sheng_process_outputv(struct proc *process, int fd, uio_t uio, unsigned mode, const char *name)
{
    if (!sheng_process_output_enabled(process, fd, mode, name)) return;
    char text[160];
    size_t count = 0;
    int index = 0, truncated = 0, vectors = uio_iovcnt(uio);
    for (; index < vectors && index < 16; index++) {
        user_addr_t address; user_size_t bytes;
        if (uio_getiov(uio, index, &address, &bytes) != 0) return;
        size_t take = bytes < 159 - count ? (size_t)bytes : 159 - count;
        if (take && copyin(address, text + count, take) != 0) return;
        count += take;
        if (bytes > take) { truncated = 1; break; }
        if (count == 159) { index++; break; }
    }
    if (count) sheng_process_output_text(process, fd, text, count, truncated || index < vectors);
}

#endif
