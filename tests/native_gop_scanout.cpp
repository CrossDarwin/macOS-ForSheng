// SPDX-License-Identifier: MIT
#include <cassert>
#include <cstdint>
#include "../platform/sheng/macos26/display/gop_scanout.h"

int main()
{
    alignas(8) uint32_t source[] = {0xff010203, 0xff112233, 0xff445566, 0xff778899, 0xffaabbcc, 0xffddeeff};
    uint32_t output[10];
    for (auto &pixel : output) pixel = 0xdeadbeef;
    nativeGopScanoutRow(output + 1, 3, reinterpret_cast<uint16_t *>(source), 6, nullptr);
    assert(output[0] == 0xdeadbeef && output[4] == 0xdeadbeef);
    assert(output[1] == source[0] && output[2] == source[2] && output[3] == source[4]);
    nativeGopScanoutRow(output + 1, 6, reinterpret_cast<uint16_t *>(source), 3, nullptr);
    for (unsigned x = 0; x < 6; x++) assert(output[x + 1] == source[x / 2]);
    assert(output[0] == 0xdeadbeef && output[7] == 0xdeadbeef);
    nativeGopScanoutRow(output, 3, reinterpret_cast<uint16_t *>(source), 5, nullptr);
    assert(output[0] == source[0] && output[1] == source[1] && output[2] == source[3]);
    nativeGopScanoutRow(output, 6, reinterpret_cast<uint16_t *>(source), 6, nullptr);
    for (unsigned x = 0; x < 6; x++) assert(output[x] == source[x]);
    uint8_t table[65536] = {};
    table[0x3c00] = 255;
    table[0x3800] = 128;
    uint16_t rgba[] = {0x3c00, 0x3800, 0, 0x3c00, 0, 0, 0x3c00, 0x3c00};
    nativeGopScanoutRow(output + 1, 1, rgba, 2, table);
    assert(output[1] == 0xffff8000);
    nativeGopScanoutRow(output, 2, rgba, 2, table);
    assert(output[0] == 0xffff8000 && output[1] == 0xff0000ff);
}
