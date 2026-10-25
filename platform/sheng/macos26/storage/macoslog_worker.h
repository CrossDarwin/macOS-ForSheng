/* SPDX-License-Identifier: MIT */
/* Included by the native UFS adapter after its bounded command helpers. */
#include "macoslog_layout.h"
extern "C" unsigned sheng_log_snapshot_copy(void *, unsigned) __attribute__((weak_import));
extern "C" {
volatile uint32_t native_macoslog_state, native_macoslog_error, native_macoslog_phase;
volatile uint64_t native_macoslog_generation, native_macoslog_snapshots, native_macoslog_busy;
volatile uint64_t native_macoslog_first_lba;
}
static const uint8_t mlFileId[16] = NATIVE_MACOSLOG_FILE_ID;
static const uint8_t mlPartitionId[16] = NATIVE_MACOSLOG_PARTITION_ID;
static const uint8_t mlTypeId[16] = NATIVE_MACOSLOG_TYPE_ID;
static IOLock *mlLifecycleLock;
static bool mlRunning;
static volatile uint32_t mlStop;

static bool mlRead(uint64_t lba, unsigned blocks, uint8_t *out) {
    IOReturn status = hostRead4k(4, lba, blocks, out);
    if (status != kIOReturnSuccess) native_macoslog_error = static_cast<uint32_t>(status);
    return status == kIOReturnSuccess;
}
static bool mlOpen(uint8_t *scratch, uint64_t &first, uint64_t &generation) {
    native_macoslog_phase = 1;
    uint8_t *other = scratch + kDataMax;
    if (!mlRead(1, 1, scratch) || !mlRead(521215, 1, other) ||
        !mlGptHeader(scratch, false) || !mlGptHeader(other, true) ||
        memcmp(scratch + 40, other + 40, 32) || ml32(scratch + 88) != ml32(other + 88)) return false;
    uint32_t crc = ml32(scratch + 88);
    uint8_t header[92]; memcpy(header, scratch, sizeof(header));
    if (!mlRead(2, 3, scratch) || mlCrc(scratch, 96*128) != crc ||
        !mlGptEntries(scratch, header, mlPartitionId, mlTypeId) ||
        !mlRead(521211, 3, other) || memcmp(scratch, other, 96*128)) return false;
    native_macoslog_phase = 2;
    MlFat geometry;
    if (!mlRead(448512, 1, scratch) || !mlFatGeometry(scratch, geometry) ||
        !mlRead(448512 + geometry.reserved, geometry.fatBlocks, scratch) ||
        !mlRead(448512 + geometry.reserved + geometry.fatBlocks, geometry.fatBlocks, other) ||
        memcmp(scratch, other, geometry.fatBlocks*4096) ||
        !mlRead(448512 + geometry.rootFirst, geometry.rootBlocks, other) ||
        !mlFile(geometry, scratch, other, first)) return false;
    native_macoslog_phase = 3;
    if (!mlRead(first + 511, 1, other) || !mlGuard(other, first, mlFileId, mlPartitionId)) return false;
    generation = 0;
    for (unsigned bank = 0; bank < 2; bank++) {
        if (!mlRead(first + bank*256, 1, other)) return false;
        if (mlCaptureHeader(other, mlFileId) && ml64(other + 16) > generation) generation = ml64(other + 16);
    }
    if (generation >= UINT64_MAX - 1) return false;
    native_macoslog_first_lba = first;
    return true;
}


static void mlThread(void *argument, wait_result_t) {
    const unsigned mode = static_cast<unsigned>(reinterpret_cast<uintptr_t>(argument));
    uint8_t *scratch = static_cast<uint8_t *>(IOMallocZero(2*kDataMax));
    uint8_t *payload = static_cast<uint8_t *>(IOMallocZero(21*4096));
    uint64_t first = 0, generation = 0, lastTotal = UINT64_MAX, lastDropped = UINT64_MAX;
    bool failed = !scratch || !payload || !sheng_log_snapshot_copy;
    native_macoslog_state = 1;
    if (!failed) failed = !mlOpen(scratch, first, generation);
    if (!failed) {
        native_macoslog_state = 2;
        IOLog("NativeUfs: macoslog file verified, mode=%u first=%llu blocks=512\n", mode, first);
    }
    if (!failed && mode == 2) failed = !hostMacosLogOpen(first, 511);
    while (!failed && mode == 2 && !__atomic_load_n(&mlStop, __ATOMIC_ACQUIRE)) {
        if (!gHost.ready || gHost.poisoned) { failed = true; break; }
        if (sheng_log_snapshot_copy(payload, 82048) != 82048) {
            native_macoslog_busy++;
            IOSleep(20);
            continue;
        }
        uint64_t total = ml64(payload + 24), dropped = ml64(payload + 32);
        if (total != lastTotal || dropped != lastDropped) {
            native_macoslog_phase = 4;
            struct Ops {
                bool write(uint64_t lba, unsigned blocks, const void *data) {
                    IOReturn r = hostWrite4k(4, lba, blocks, data);
                    if (r != kIOReturnSuccess) native_macoslog_error = static_cast<uint32_t>(r);
                    return r == kIOReturnSuccess;
                }
                bool sync() {
                    IOReturn r = hostMacosLogSync();
                    if (r != kIOReturnSuccess) native_macoslog_error = static_cast<uint32_t>(r);
                    return r == kIOReturnSuccess;
                }
            } ops;
            if (generation >= UINT64_MAX - 1 || !mlCommit(ops, first, generation + 1, payload, scratch, mlFileId)) { failed = true; break; }
            generation++; native_macoslog_generation = generation; native_macoslog_snapshots++;
            native_macoslog_state = 3; lastTotal = total; lastDropped = dropped;
            if (native_macoslog_snapshots == 1)
                IOLog("NativeUfs: macoslog first snapshot committed, generation=%llu\n", generation);
        }
        IOSleep(2000);
    }
    if (failed) {
        native_macoslog_state = 5;
        IOLog("NativeUfs: macoslog stopped phase=%u error=%08x; no write retry\n", native_macoslog_phase, native_macoslog_error);
    }
    if (payload) IOFree(payload, 21*4096);
    if (scratch) IOFree(scratch, 2*kDataMax);
    IOLockLock(mlLifecycleLock); mlRunning = false; IOLockWakeup(mlLifecycleLock, &mlRunning, false); IOLockUnlock(mlLifecycleLock);
    thread_terminate(current_thread());
}
static void mlStart(void) {
    unsigned mode = 0;
    if (!PE_parse_boot_argn("native-ufs-macoslog", &mode, sizeof(mode)) || mode < 1 || mode > 2) return;
    mlLifecycleLock = IOLockAlloc();
    if (!mlLifecycleLock) { native_macoslog_state = 5; return; }
    __atomic_store_n(&mlStop, 0, __ATOMIC_RELEASE);
    thread_t thread = nullptr; mlRunning = true;
    if (kernel_thread_start(mlThread, reinterpret_cast<void *>(static_cast<uintptr_t>(mode)), &thread) != KERN_SUCCESS) {
        mlRunning = false; native_macoslog_state = 5; IOLockFree(mlLifecycleLock); mlLifecycleLock = nullptr; return;
    }
    thread_deallocate(thread);
}
static void mlShutdown(void) {
    if (!mlLifecycleLock) return;
    __atomic_store_n(&mlStop, 1, __ATOMIC_RELEASE);
    IOLockLock(mlLifecycleLock);
    while (mlRunning) IOLockSleep(mlLifecycleLock, &mlRunning, THREAD_UNINT);
    IOLockUnlock(mlLifecycleLock); IOLockFree(mlLifecycleLock); mlLifecycleLock = nullptr;
    gMacosLogOpen = false;
}
