/* SPDX-License-Identifier: MIT */
#ifndef SHENG_CRYPTO_IMAGE_H
#define SHENG_CRYPTO_IMAGE_H
#include <libkern/section_keywords.h>
#include <mach-o/loader.h>

extern char sheng_cc26_text_start[] __SECTION_START_SYM("__TEXT_EXEC", "__cc26_text");
extern char sheng_cc26_text_end[] __SECTION_END_SYM("__TEXT_EXEC", "__cc26_text");

/* Expose the provider-owned Mach-O code view so POST excludes XNU code modified by static_if. */
struct sheng_crypto_image {
    struct mach_header_64 header;
    struct segment_command_64 text;
    struct segment_command_64 code;
    struct section_64 section;
};
static SECURITY_READ_ONLY_LATE(struct sheng_crypto_image) sheng_crypto_image = {
    .header = {.magic = MH_MAGIC_64, .cputype = CPU_TYPE_ARM64,
               .cpusubtype = CPU_SUBTYPE_ARM64_ALL, .filetype = MH_KEXT_BUNDLE,
               .ncmds = 2, .sizeofcmds = 2 * sizeof(struct segment_command_64) + sizeof(struct section_64),
               .flags = MH_DYLIB_IN_CACHE},
    .text = {.cmd = LC_SEGMENT_64, .cmdsize = sizeof(struct segment_command_64),
             .segname = "__TEXT", .maxprot = VM_PROT_READ, .initprot = VM_PROT_READ},
    .code = {.cmd = LC_SEGMENT_64, .cmdsize = sizeof(struct segment_command_64) + sizeof(struct section_64),
             .segname = "__TEXT_EXEC", .maxprot = VM_PROT_READ | VM_PROT_EXECUTE,
             .initprot = VM_PROT_READ | VM_PROT_EXECUTE, .nsects = 1},
    .section = {.sectname = "__text", .segname = "__TEXT_EXEC", .align = 2,
                .flags = S_REGULAR | S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS},
};

static vm_address_t
sheng_crypto_image_prepare(void)
{
    uint64_t base = (uintptr_t)&sheng_crypto_image;
    uint64_t start = (uintptr_t)sheng_cc26_text_start;
    uint64_t end = (uintptr_t)sheng_cc26_text_end;
    if (start < base + sizeof(sheng_crypto_image) || end <= start) {
        panic("SHENG corecrypto has invalid module text bounds");
    }
    sheng_crypto_image.text.vmaddr = base;
    sheng_crypto_image.text.vmsize = sizeof(sheng_crypto_image);
    sheng_crypto_image.text.filesize = sizeof(sheng_crypto_image);
    sheng_crypto_image.code.vmaddr = start;
    sheng_crypto_image.code.vmsize = end - start;
    sheng_crypto_image.code.filesize = end - start;
    sheng_crypto_image.section.addr = start;
    sheng_crypto_image.section.size = end - start;
    return (vm_address_t)base;
}
#endif
