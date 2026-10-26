// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include <cstdint>
#include <vector>
#include "../platform/sheng/macos26/display/gop_scanout.h"
#include "../platform/sheng/macos26/display/gop_layers.h"

int main()
{
    NativeGopSwapLayer layers[kNativeGopSwapLayerCount] = {
        {128, 128, 0x42475241}, {1600, 1200, 0x42475241},
        {800, 600, 0x52476841}, {16384, 16384, 0}
    };
    // The cursor occupies layer zero after a session transition.
    assert(nativeGopScanoutLayer(layers, 3, 800, 600) == 1);
    assert(nativeGopScanoutLayer(layers, 1, 800, 600) == -1);
    assert(nativeGopScanoutLayer(layers, 4, 800, 600) == 2);
    assert(nativeGopScanoutLayer(layers, 15, 800, 600) == 1);
    assert(nativeGopScanoutLayer(layers, 0xf0, 800, 600) == -1);
    assert(nativeGopScanoutLayer(layers, 15, 0, 600) == -1);
    layers[1].width = UINT64_MAX;
    assert(nativeGopScanoutLayer(layers, 15, 800, 600) == 2);
    layers[1] = {800, 600, 0x42475241};
    assert(nativeGopScanoutLayer(layers, 6, 800, 600) == 1);
    layers[1] = {400, 300, 0x42475241};
    assert(nativeGopScanoutLayer(layers, 2, 800, 600) == 1);
    layers[1] = {100, 75, 0x42475241};
    assert(nativeGopScanoutLayer(layers, 2, 800, 600) == -1);
    layers[1] = {6096, 4064, 0x42475241};
    assert(nativeGopScanoutLayer(layers, 3, 3048, 2032) == 1);

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

    // The physical sheng panel is 3048x2032; exercise its doubled backing rows and padded scanout.
    constexpr uint64_t panelWidth = 3048, panelHeight = 2032;
    constexpr uint64_t backingWidth = panelWidth * 2, backingHeight = panelHeight * 2;
    std::vector<uint32_t> backing(backingWidth), scanout(panelWidth + 16, 0xdeadbeef);
    const uint64_t rows[] = {0, 1, panelHeight / 2, panelHeight - 1};
    for (uint64_t y : rows) {
        uint64_t sourceY = y * backingHeight / panelHeight;
        for (uint64_t x = 0; x < backingWidth; x++)
            backing[x] = 0xff000000 | static_cast<uint32_t>((sourceY * backingWidth + x) & 0xffffff);
        nativeGopScanoutRow(scanout.data() + 8, panelWidth,
                            reinterpret_cast<uint16_t *>(backing.data()), backingWidth, nullptr);
        for (uint64_t x = 0; x < panelWidth; x++) assert(scanout[x + 8] == backing[x * 2]);
        for (uint64_t x = 0; x < 8; x++)
            assert(scanout[x] == 0xdeadbeef && scanout[x + panelWidth + 8] == 0xdeadbeef);
    }
}
