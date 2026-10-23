// SPDX-License-Identifier: MIT
// PID1只读指定的保留RAM，通过只读USB磁盘导出，不打开UFS块设备
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef LOG_BASE
#error LOG_BASE must come from the observed native kernel load address
#endif
#define LOG_BYTES 82048
#define LOG_ALLOC_BYTES ((LOG_BYTES + 511) / 512 * 512)
#define FAT_DATA_OFFSET (17 * 512)

static int put(const char *path, const char *text)
{
    int fd = open(path, O_WRONLY | O_CLOEXEC);
    if (fd < 0) {
        dprintf(2, "SHENG-NATIVE-READER: open %s errno=%d\n", path, errno);
        return -1;
    }
    size_t size = strlen(text);
    ssize_t done = write(fd, text, size);
    int saved = errno;
    if (done != (ssize_t)size)
        dprintf(2, "SHENG-NATIVE-READER: write %s errno=%d bytes=%zd\n", path, saved, done);
    close(fd);
    errno = saved;
    return done == (ssize_t)size ? 0 : -1;
}

static uint32_t crc32(const unsigned char *data, size_t size)
{
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ ((crc & 1) ? UINT32_C(0xedb88320) : 0);
    }
    return ~crc;
}

static int subdir(const char *path)
{
    int result = mkdir(path, 0755);
    if (result) dprintf(2, "SHENG-NATIVE-READER: mkdir %s errno=%d\n", path, errno);
    return result;
}

static int snapshot(void)
{
    unsigned char bytes[LOG_BYTES] = {0};
    int error = 0;
    int mem = open("/dev/mem", O_RDONLY | O_CLOEXEC | O_SYNC);
    if (mem < 0) error = errno;
    else {
        void *mapped = mmap(NULL, sizeof(bytes), PROT_READ, MAP_SHARED, mem, (off_t)LOG_BASE);
        if (mapped == MAP_FAILED) error = errno;
        else {
            memcpy(bytes, mapped, sizeof(bytes));
            munmap(mapped, sizeof(bytes));
        }
        close(mem);
    }
    char status[1024] = {0};
    snprintf(status, sizeof(status),
             "reader=sheng-native-reader-v1\nphysical_base=0x%llx\nbytes=%u\nerrno=%d\ncrc32=%08x\n"
             "storage=RAM-backed read-only USB export\nufs_opened=false\n",
             (unsigned long long)LOG_BASE, LOG_BYTES, error, crc32(bytes, sizeof(bytes)));
    int fd = open("/ramlog.img", O_RDWR | O_CLOEXEC);
    if (fd < 0) return -1;
    int result = pwrite(fd, bytes, sizeof(bytes), FAT_DATA_OFFSET) != sizeof(bytes)
              || pwrite(fd, status, sizeof(status), FAT_DATA_OFFSET + LOG_ALLOC_BYTES) != sizeof(status)
              || fsync(fd) != 0;
    close(fd);
    dprintf(2, "SHENG-NATIVE-READER: snapshot errno=%d crc32=%08x\n", error, crc32(bytes, sizeof(bytes)));
    return result ? -1 : 0;
}

static void load_reset_module(void)
{
    int fd = open("/nvmem-reboot-mode.ko", O_RDONLY | O_CLOEXEC);
    if (fd >= 0) {
        if (syscall(SYS_finit_module, fd, "", 0) != 0)
            dprintf(2, "SHENG-NATIVE-READER: reset module errno=%d\n", errno);
        close(fd);
    }
}

static int usb_disk(void)
{
    glob_t roles = {0};
    if (glob("/sys/class/usb_role/*/role", 0, NULL, &roles) == 0)
        for (size_t i = 0; i < roles.gl_pathc; i++) put(roles.gl_pathv[i], "device");
    globfree(&roles);
    const char *base = "/config/usb_gadget/ramlog";
    if (mkdir(base, 0755) || chdir(base)) {
        dprintf(2, "SHENG-NATIVE-READER: gadget directory errno=%d\n", errno);
        return -1;
    }
    if (subdir("strings/0x409") || subdir("configs/c.1")
            || subdir("functions/mass_storage.0")) return -1;
    if (put("idVendor", "0x1d6b") || put("idProduct", "0x0104")
            || put("strings/0x409/serialnumber", "shengnativelog")
            || put("strings/0x409/manufacturer", "Sheng diagnostics")
            || put("strings/0x409/product", "Sheng RAM log")
            || put("functions/mass_storage.0/lun.0/ro", "1")
            || put("functions/mass_storage.0/lun.0/file", "/ramlog.img")) return -1;
    if (symlink("/config/usb_gadget/ramlog/functions/mass_storage.0", "configs/c.1/log")) {
        dprintf(2, "SHENG-NATIVE-READER: function link errno=%d\n", errno);
        return -1;
    }
    for (unsigned attempt = 0; attempt < 30; attempt++) {
        DIR *directory = opendir("/sys/class/udc");
        if (directory) {
            struct dirent *entry;
            while ((entry = readdir(directory))) {
                if (entry->d_name[0] != '.') {
                    int result = put("UDC", entry->d_name);
                    closedir(directory);
                    return result;
                }
            }
            closedir(directory);
        }
        sleep(1);
    }
    return -1;
}

int main(void)
{
    const char *dirs[] = {"/dev", "/proc", "/sys", "/run", "/config"};
    for (size_t i = 0; i < sizeof(dirs)/sizeof(dirs[0]); i++) mkdir(dirs[i], 0755);
    mount("devtmpfs", "/dev", "devtmpfs", 0, "");
    int console = open("/dev/console", O_RDWR);
    if (console >= 0) {
        dup2(console, 0); dup2(console, 1); dup2(console, 2);
        if (console > 2) close(console);
    }
    if (mount("proc", "/proc", "proc", 0, "") || mount("sysfs", "/sys", "sysfs", 0, ""))
        dprintf(2, "SHENG-NATIVE-READER: proc/sysfs mount errno=%d\n", errno);
    load_reset_module();
    int result = snapshot();
    int config_status = mount("configfs", "/config", "configfs", 0, "");
    if (config_status) dprintf(2, "SHENG-NATIVE-READER: configfs mount errno=%d\n", errno);
    if (config_status || usb_disk())
        dprintf(2, "SHENG-NATIVE-READER: USB export unavailable errno=%d\n", errno);
    else dprintf(2, "SHENG-NATIVE-READER: read-only USB disk ready snapshot=%d\n", result);
    sleep(90);
    syscall(SYS_sync);
    syscall(SYS_reboot, 0xfee1dead, 672274793, 0xa1b2c3d4, "bootloader");
    for (;;) sleep(60);
}
