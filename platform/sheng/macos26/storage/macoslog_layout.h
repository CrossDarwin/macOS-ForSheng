/* SPDX-License-Identifier: MIT */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

static inline uint16_t ml16(const uint8_t *p) { uint16_t v; memcpy(&v, p, 2); return v; }
static inline uint32_t ml32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static inline uint64_t ml64(const uint8_t *p) { uint64_t v; memcpy(&v, p, 8); return v; }
static inline void mlPut32(uint8_t *p, uint32_t v) { memcpy(p, &v, 4); }
static inline void mlPut64(uint8_t *p, uint64_t v) { memcpy(p, &v, 8); }
static inline uint32_t mlCrc(const uint8_t *p, size_t n) {
    uint32_t crc = 0xffffffffu;
    while (n--) { crc ^= *p++; for (unsigned i = 0; i < 8; i++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1))); }
    return ~crc;
}
static inline bool mlGptHeader(const uint8_t *p, bool backup) {
    if (memcmp(p, "EFI PART", 8) || ml32(p + 8) != 0x10000 || ml32(p + 12) != 92 ||
        ml32(p + 20) || ml64(p + 24) != (backup ? 521215u : 1u) ||
        ml64(p + 32) != (backup ? 1u : 521215u) || ml32(p + 80) != 96 || ml32(p + 84) != 128 ||
        ml64(p + 40) > 448512 || ml64(p + 48) < 464895 || ml64(p + 48) >= 521215 ||
        ml64(p + 72) != (backup ? 521211u : 2u)) return false;
    uint8_t copy[92]; memcpy(copy, p, sizeof(copy)); memset(copy + 16, 0, 4);
    return ml32(p + 16) == mlCrc(copy, sizeof(copy));
}
static inline bool mlGptEntries(const uint8_t *p, const uint8_t *header,
                              const uint8_t *partitionId, const uint8_t *typeId) {
    if (mlCrc(p, 96 * 128) != ml32(header + 88)) return false;
    unsigned matches = 0;
    for (unsigned i = 0; i < 96; i++) {
        const uint8_t *e = p + i * 128;
        uint8_t used = 0; for (unsigned j = 0; j < 16; j++) used |= e[j];
        if (!used) continue;
        uint64_t low = ml64(e + 32), high = ml64(e + 40);
        if (low > high || low < ml64(header + 40) || high > ml64(header + 48)) return false;
        if (!memcmp(e + 16, partitionId, 16)) {
            static const uint16_t name[36] = {'m','a','c','o','s','l','o','g',0};
            if (i != 77 || memcmp(e, typeId, 16) || low != 448512 || high != 464895 ||
                memcmp(e + 56, name, sizeof(name))) return false;
            matches++;
        } else if (low <= 464895 && high >= 448512) return false;
    }
    return matches == 1;
}
struct MlFat {
    uint32_t reserved, fatBlocks, rootFirst, rootBlocks, dataFirst, clusterBlocks, clusters;
};
static inline bool mlFatGeometry(const uint8_t *p, MlFat &g) {
    if (ml16(p + 11) != 4096 || p[16] != 2 || ml16(p + 19) != 16384 || ml32(p + 32) != 0 ||
        memcmp(p + 43, "MACOSLOG   ", 11) || memcmp(p + 54, "FAT16   ", 8) || ml16(p + 510) != 0xaa55) return false;
    g.reserved = ml16(p + 14); g.fatBlocks = ml16(p + 22); g.clusterBlocks = p[13];
    const uint32_t entries = ml16(p + 17);
    if (!g.reserved || !g.fatBlocks || g.fatBlocks > 32 || !entries || entries % 128 || entries > 1024 ||
        !g.clusterBlocks || (g.clusterBlocks & (g.clusterBlocks - 1)) || g.clusterBlocks > 8) return false;
    g.rootFirst = g.reserved + 2 * g.fatBlocks; g.rootBlocks = entries / 128;
    g.dataFirst = g.rootFirst + g.rootBlocks;
    if (g.dataFirst >= 16384) return false;
    g.clusters = (16384 - g.dataFirst) / g.clusterBlocks;
    return g.clusters >= 4085 && g.clusters < 65525 && (g.clusters + 2) * 2 <= g.fatBlocks * 4096;
}
/* A contiguous owned file permits data-only writes without an in-kernel FAT allocator. */
static inline bool mlFile(const MlFat &g, const uint8_t *fat, const uint8_t *root, uint64_t &first) {
    unsigned matches = 0; uint32_t cluster = 0;
    for (unsigned i = 0; i < g.rootBlocks * 4096; i += 32) {
        const uint8_t *entry = root + i;
        if (!entry[0]) break;
        if (entry[0] == 0xe5 || entry[11] == 0x0f || memcmp(entry, "SHENGLOGBIN", 11)) continue;
        if ((entry[11] & 0x19) || ml16(entry + 20) || ml32(entry + 28) != 2097152) return false;
        cluster = ml16(entry + 26); matches++;
    }
    if (matches != 1 || cluster < 2 || 512 % g.clusterBlocks) return false;
    const uint32_t count = 512 / g.clusterBlocks;
    if (cluster >= g.clusters + 2 || count > g.clusters + 2 - cluster) return false;
    for (uint32_t i = 0; i < count; i++) {
        uint16_t next = ml16(fat + (cluster + i) * 2);
        if (i + 1 == count ? next < 0xfff8 : next != cluster + i + 1) return false;
    }
    /* Reject cross-links, including another root entry naming any owned cluster. */
    for (uint32_t i = 2; i < g.clusters + 2; i++) {
        uint16_t next = ml16(fat + i * 2);
        if (next >= cluster && next < cluster + count && (next == cluster || i != uint32_t(next) - 1)) return false;
    }
    for (unsigned i = 0; i < g.rootBlocks * 4096; i += 32) {
        const uint8_t *e = root + i;
        if (!e[0]) break;
        if (e[0] == 0xe5 || e[11] == 0x0f || !memcmp(e, "SHENGLOGBIN", 11)) continue;
        uint32_t other = ml16(e + 26);
        if (other >= cluster && other < cluster + count) return false;
    }
    first = 448512 + g.dataFirst + (cluster - 2) * g.clusterBlocks;
    return first > 448512 && first + 512 <= 464896;
}
static inline bool mlGuard(const uint8_t *p, uint64_t first, const uint8_t *fileId, const uint8_t *partitionId) {
    return !memcmp(p, "SHNGSLOT", 8) && ml32(p + 8) == 1 && ml32(p + 12) == 4096 &&
        !memcmp(p + 16, fileId, 16) && !memcmp(p + 32, partitionId, 16) &&
        ml64(p + 48) == first && ml64(p + 56) == 512 && ml64(p + 64) == 82048 &&
        ml32(p + 4092) == mlCrc(p, 4092);
}
static inline bool mlCaptureHeader(const uint8_t *p, const uint8_t *fileId) {
    return !memcmp(p, "SHNCAP01", 8) && ml32(p + 8) == 1 && ml32(p + 12) == 4096 &&
        ml64(p + 16) && ml64(p + 16) != UINT64_MAX && ml32(p + 24) == 82048 &&
        !memcmp(p + 64, fileId, 16) && ml32(p + 4092) == mlCrc(p, 4092);
}

/* Flush payload before publishing its header; the other bank survives any incomplete round. */
template<class Ops>
static bool mlCommit(Ops &ops, uint64_t first, uint64_t generation, uint8_t *payload, uint8_t *header, const uint8_t *fileId) {
    if (!generation || generation == UINT64_MAX) return false;
    uint64_t at = first + (generation & 1)*256;
    if (!ops.write(at + 1, 21, payload) || !ops.sync()) return false;
    memset(header, 0, 4096);
    memcpy(header, "SHNCAP01", 8); mlPut32(header + 8, 1); mlPut32(header + 12, 4096);
    mlPut64(header + 16, generation); mlPut32(header + 24, 82048);
    mlPut32(header + 28, mlCrc(payload, 82048)); memcpy(header + 32, payload + 112, 16);
    memcpy(header + 48, payload + 24, 16); memcpy(header + 64, fileId, 16);
    mlPut32(header + 4092, mlCrc(header, 4092));
    return ops.write(at, 1, header) && ops.sync();
}

