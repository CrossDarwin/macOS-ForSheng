// SPDX-License-Identifier: GPL-3.0-or-later
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/evp.h>
#include "../platform/sheng/macos26/recovery/ui_policy.h"
#include "sheng_recovery_ui_pages.h"

static void digest(const void *data, size_t size, uint8_t result[32])
{
    unsigned int length = 0;
    assert(EVP_Digest(data, size, result, &length, EVP_sha256(), NULL));
    assert(length == 32);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    unsigned long index = strtoul(argv[1], NULL, 10);
    assert(index < sizeof(sheng_ui_pages) / sizeof(sheng_ui_pages[0]));
    struct sheng_ui_page rule = sheng_ui_pages[index];
    uint8_t memory[SHENG_UI_PAGE_BYTES + 32], original[SHENG_UI_PAGE_BYTES];
    memset(memory, 0xad, sizeof(memory));
    uint8_t *page = memory + 16;
    FILE *stream = fopen(argv[2], "rb");
    assert(stream && fread(page, 1, SHENG_UI_PAGE_BYTES, stream) == SHENG_UI_PAGE_BYTES);
    assert(fclose(stream) == 0);
    memcpy(original, page, sizeof(original));

    assert(sheng_ui_apply_page(page, sizeof(original) - 1, &rule, digest) == -1);
    page[rule.edits[0].offset] ^= 1;
    assert(sheng_ui_apply_page(page, sizeof(original), &rule, digest) == -1);
    assert(page[rule.edits[0].offset] == (uint8_t)(original[rule.edits[0].offset] ^ 1));
    memcpy(page, original, sizeof(original));
    struct sheng_ui_page invalid = rule;
    invalid.edits[0].before[0] ^= 1;
    assert(sheng_ui_apply_page(page, sizeof(original), &invalid, digest) == -1);
    assert(!memcmp(page, original, sizeof(original)));
    invalid = rule;
    invalid.edits[0].offset = SHENG_UI_PAGE_BYTES;
    assert(sheng_ui_apply_page(page, sizeof(original), &invalid, digest) == -1);
    invalid = rule;
    invalid.edits[1] = invalid.edits[0];
    invalid.edit_count = 2;
    assert(sheng_ui_apply_page(page, sizeof(original), &invalid, digest) == -1);
    assert(!memcmp(page, original, sizeof(original)));
    invalid = rule;
    invalid.after_sha256[0] ^= 1;
    assert(sheng_ui_apply_page(page, sizeof(original), &invalid, digest) == -1);
    assert(!memcmp(page, original, sizeof(original)));

    assert(sheng_ui_apply_page(page, sizeof(original), &rule, digest) == 1);
    assert(sheng_ui_apply_page(page, sizeof(original), &rule, digest) == 0);
    for (unsigned int i = 0; i < 16; i++)
        assert(memory[i] == 0xad && memory[sizeof(memory) - i - 1] == 0xad);
    for (unsigned int i = 0; i < SHENG_UI_PAGE_BYTES; i++) {
        int edited = 0;
        for (unsigned int j = 0; j < rule.edit_count; j++)
            edited |= i >= rule.edits[j].offset && i < rule.edits[j].offset + rule.edits[j].size;
        if (!edited)
            assert(page[i] == original[i]);
    }
    return 0;
}
