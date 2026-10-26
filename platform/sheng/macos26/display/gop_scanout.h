// SPDX-License-Identifier: MIT
#pragma once

// The root IOSurface can have a different backing scale from the scanout.
// Select source pixels before format conversion; never relabel its storage.
// The caller validates nonzero extents and supplies a complete source row.
static inline void nativeGopScanoutRow(uint32_t *destination, uint64_t destinationWidth,
                                     const uint16_t *source, uint64_t sourceWidth,
                                     const uint8_t *halfToByte)
{
    uint64_t sourceX = 0, remainder = 0;
    const uint64_t step = sourceWidth / destinationWidth;
    const uint64_t fraction = sourceWidth % destinationWidth;
    for (uint64_t x = 0; x < destinationWidth; x++) {
        if (halfToByte) {
            const uint16_t *rgba = source + sourceX * 4;
            destination[x] = 0xff000000u | static_cast<uint32_t>(halfToByte[rgba[0]]) << 16 |
                             static_cast<uint32_t>(halfToByte[rgba[1]]) << 8 | halfToByte[rgba[2]];
        } else {
            destination[x] = reinterpret_cast<const uint32_t *>(source)[sourceX];
        }
        sourceX += step;
        remainder += fraction;
        if (remainder >= destinationWidth) {
            sourceX++;
            remainder -= destinationWidth;
        }
    }
}
