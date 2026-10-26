// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

enum { kNativeGopSwapLayerCount = 4 };

struct NativeGopSwapLayer {
    uint64_t width, height;
    uint32_t format;
};

// A session transition can move scanout away from layer zero. Cursor-only
// updates must not replace the full frame with a small surface.
static inline int nativeGopScanoutLayer(const NativeGopSwapLayer *layers, uint8_t mask,
                                       uint64_t width, uint64_t height)
{
    if (!width || !height || width > 16384 || height > 16384)
        return -1;
    int selected = -1;
    uint64_t largest = 0;
    for (unsigned i = 0; i < kNativeGopSwapLayerCount; i++) {
        const auto &layer = layers[i];
        if (!(mask & (1u << i)) || !layer.width || !layer.height ||
            layer.width > 16384 || layer.height > 16384 ||
            (layer.format != 0x42475241 && layer.format != 0x52476841) ||
            layer.width * height != layer.height * width ||
            layer.width > width * 4 || layer.height > height * 4 ||
            width > layer.width * 4 || height > layer.height * 4)
            continue;
        uint64_t area = layer.width * layer.height;
        if (area > largest) {
            largest = area;
            selected = static_cast<int>(i);
        }
    }
    return selected;
}
