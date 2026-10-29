// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <vm/sheng_language_trace.h>
#define SHENG_LANGUAGE_TRACE_PAGE_TABLE
#include <vm/sheng_language_trace_pages.h>
#undef SHENG_LANGUAGE_TRACE_PAGE_TABLE

extern uint32_t sheng_language_trace_enabled;

static void
sheng_language_trace_page(vm_page_t page, struct vnode *vnode, uint64_t offset, bool validated)
{
    if (sheng_language_trace_enabled != 1)
        return;
    const size_t count = sizeof(sheng_language_trace_pages) / sizeof(sheng_language_trace_pages[0]);
    for (size_t i = 0; i < count; i++) {
        const struct sheng_ui_page *rule = &sheng_language_trace_pages[i];
        if (offset != rule->file_offset)
            continue;
        const char *name = vnode_getname(vnode);
        if (!name)
            return;
        bool match = !strcmp(name, rule->file);
        vnode_putname(name);
        if (!match)
            return;
        if (PAGE_SIZE != SHENG_UI_PAGE_BYTES || csr_check(CSR_ALLOW_UNAUTHENTICATED_ROOT) ||
            !validated || page->vmp_cs_validated != VMP_CS_ALL_TRUE ||
            page->vmp_cs_tainted != VMP_CS_ALL_FALSE || page->vmp_cs_nx != VMP_CS_ALL_FALSE ||
            page->vmp_dirty || page->vmp_wpmapped)
            panic("SHENG: Language trace requires an authenticated immutable development page");
        uint8_t *bytes = (uint8_t *)phystokv((pmap_paddr_t)VM_PAGE_GET_PHYS_PAGE(page) << PAGE_SHIFT);
        int result = sheng_ui_apply_page(bytes, PAGE_SIZE, rule, sheng_recovery_ui_digest);
        if (result < 0)
            panic("SHENG: Language trace page %zu differs from 25F71", i);
        if (result) {
            cache_sync_page(VM_PAGE_GET_PHYS_PAGE(page));
            printf("SHENG-LANGUAGE: trace page %zu installed\n", i);
        }
        return;
    }
}
