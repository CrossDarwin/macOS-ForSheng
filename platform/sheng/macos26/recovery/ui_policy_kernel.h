// SPDX-License-Identifier: MIT
#pragma once

#include <arm/caches_internal.h>
#include <libkern/crypto/sha2.h>
#include <sys/csr.h>
#include <sys/vnode.h>
#include <vm/sheng_recovery_ui.h>
#include <vm/sheng_recovery_ui_pages.h>

TUNABLE(uint32_t, sheng_recovery_ui_enabled, "sheng-recovery-ui", 0);
volatile uint32_t sheng_recovery_ui_pages_applied;
volatile uint32_t sheng_recovery_ui_page_mask;

static void
sheng_recovery_ui_digest(const void *data, size_t size, uint8_t result[32])
{
    SHA256_CTX context;
    SHA256_Init(&context);
    SHA256_Update(&context, data, size);
    SHA256_Final(result, &context);
}

static void
sheng_recovery_ui_page(vm_page_t page, struct vnode *vnode, uint64_t offset)
{
    if (!sheng_recovery_ui_enabled)
        return;
    const size_t count = sizeof(sheng_ui_pages) / sizeof(sheng_ui_pages[0]);
    bool candidate = false;
    for (size_t i = 0; i < count; i++)
        candidate |= offset == sheng_ui_pages[i].file_offset;
    if (!candidate)
        return;
    const char *name = vnode_getname(vnode);
    if (!name)
        return;
    for (size_t i = 0; i < count; i++) {
        const struct sheng_ui_page *rule = &sheng_ui_pages[i];
        if (offset != rule->file_offset || strcmp(name, rule->file))
            continue;
        vnode_putname(name);
        // Never turn a failed signature, writable page, or production boot into an accepted image.
        if (sheng_recovery_ui_enabled != 1 || PAGE_SIZE != SHENG_UI_PAGE_BYTES ||
            csr_check(CSR_ALLOW_UNAUTHENTICATED_ROOT) != 0 ||
            page->vmp_cs_validated != VMP_CS_ALL_TRUE || page->vmp_cs_tainted != VMP_CS_ALL_FALSE ||
            page->vmp_cs_nx != VMP_CS_ALL_FALSE || page->vmp_dirty || page->vmp_wpmapped)
            panic("SHENG: Recovery UI policy %zu requires an authenticated immutable development page", i);
        // The validation mapping can be read-only; write through the owned busy physical page instead.
        uint8_t *bytes = (uint8_t *)phystokv((pmap_paddr_t)VM_PAGE_GET_PHYS_PAGE(page) << PAGE_SHIFT);
        int result = sheng_ui_apply_page(bytes, PAGE_SIZE, rule, sheng_recovery_ui_digest);
        if (result < 0)
            panic("SHENG: Recovery UI policy %zu page digest or instructions differ", i);
        if (result) {
            flush_dcache64((addr64_t)bytes, PAGE_SIZE, FALSE);
            invalidate_icache64((addr64_t)bytes, PAGE_SIZE, FALSE);
            OSAddAtomic(1, (volatile SInt32 *)&sheng_recovery_ui_pages_applied);
            OSBitOrAtomic((uint32_t)1 << i, &sheng_recovery_ui_page_mask);
            printf("SHENG: Recovery UI policy %zu applied - authenticated memory only\n", i);
        }
        return;
    }
    vnode_putname(name);
}
