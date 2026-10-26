// SPDX-License-Identifier: MIT
#pragma once

#define SHENG_UI_PAGE_BYTES 16384u
#define SHENG_UI_MAX_EDITS 4u
#define SHENG_UI_MAX_EDIT_BYTES 16u

struct sheng_ui_edit {
    uint32_t offset;
    uint32_t size;
    uint8_t before[SHENG_UI_MAX_EDIT_BYTES];
    uint8_t after[SHENG_UI_MAX_EDIT_BYTES];
};

struct sheng_ui_page {
    const char *file;
    uint64_t file_offset;
    uint8_t before_sha256[32];
    uint8_t after_sha256[32];
    uint32_t edit_count;
    struct sheng_ui_edit edits[SHENG_UI_MAX_EDITS];
};

typedef void (*sheng_ui_digest)(const void *, size_t, uint8_t[32]);

// The caller owns a busy, originally authenticated page under its object lock.
// Check the whole page and every edit before writing; retain original disk data.
// Return 1 for a new application, 0 for an already applied page, -1 on mismatch.
static inline int
sheng_ui_apply_page(uint8_t *page, size_t size, const struct sheng_ui_page *rule,
                   sheng_ui_digest digest)
{
    uint8_t hash[32];
    if (size != SHENG_UI_PAGE_BYTES || !rule->edit_count || rule->edit_count > SHENG_UI_MAX_EDITS)
        return -1;
    for (uint32_t i = 0; i < rule->edit_count; i++) {
        const struct sheng_ui_edit *edit = &rule->edits[i];
        if (!edit->size || edit->size > SHENG_UI_MAX_EDIT_BYTES || (edit->size | edit->offset) & 3u ||
            edit->offset > SHENG_UI_PAGE_BYTES - edit->size)
            return -1;
        for (uint32_t j = 0; j < i; j++) {
            const struct sheng_ui_edit *other = &rule->edits[j];
            if (edit->offset < other->offset + other->size && other->offset < edit->offset + edit->size)
                return -1;
        }
    }
    digest(page, size, hash);
    if (!memcmp(hash, rule->after_sha256, sizeof(hash)))
        return 0;
    if (memcmp(hash, rule->before_sha256, sizeof(hash)))
        return -1;
    for (uint32_t i = 0; i < rule->edit_count; i++) {
        const struct sheng_ui_edit *edit = &rule->edits[i];
        if (memcmp(page + edit->offset, edit->before, edit->size))
            return -1;
    }
    for (uint32_t i = 0; i < rule->edit_count; i++) {
        const struct sheng_ui_edit *edit = &rule->edits[i];
        memcpy(page + edit->offset, edit->after, edit->size);
    }
    digest(page, size, hash);
    if (!memcmp(hash, rule->after_sha256, sizeof(hash)))
        return 1;
    for (uint32_t i = 0; i < rule->edit_count; i++) {
        const struct sheng_ui_edit *edit = &rule->edits[i];
        memcpy(page + edit->offset, edit->before, edit->size);
    }
    return -1;
}
