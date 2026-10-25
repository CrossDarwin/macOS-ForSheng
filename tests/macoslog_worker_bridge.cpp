// SPDX-License-Identifier: MIT
// Replace OS scheduling and transport only; run the production worker and layout checks.
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
using IOReturn = uint32_t;
constexpr IOReturn kIOReturnSuccess=0, kIOReturnIOError=1;
constexpr unsigned kDataMax=131072;
struct { bool ready=true, poisoned=false; } gHost;
static bool gMacosLogOpen;
static unsigned mode, writeCalls, syncCalls, failWrite, allocated, freed;
static uint64_t fileFirst;
static uint8_t *image;
static const uint8_t *primary, *backup, *entries, *snapshot;
static IOReturn hostRead4k(uint8_t lun, uint64_t lba, unsigned blocks, void *out) {
    assert(lun == 4 && blocks && blocks <= 32);
    const uint8_t *source = nullptr;
    if (lba == 1 && blocks == 1) source=primary;
    if (lba == 521215 && blocks == 1) source=backup;
    if ((lba == 2 || lba == 521211) && blocks == 3) source=entries;
    if (lba >= 448512 && lba + blocks <= 464896) source=image+(lba-448512)*4096;
    if (!source) return kIOReturnIOError;
    memcpy(out, source, blocks*4096);
    return 0;
}
static bool hostMacosLogOpen(uint64_t first, uint64_t blocks) {
    assert(!gMacosLogOpen && blocks == 511 && first > 448512 && first+512 <= 464896);
    fileFirst=first; gMacosLogOpen=true; return true;
}
static IOReturn hostWrite4k(uint8_t lun, uint64_t lba, unsigned blocks, const void *data) {
    assert(gMacosLogOpen && lun == 4 && lba >= fileFirst && lba+blocks <= fileFirst+511);
    if (++writeCalls == failWrite) return kIOReturnIOError;
    memcpy(image+(lba-448512)*4096, data, blocks*4096); return 0;
}
static IOReturn hostMacosLogSync() { assert(gMacosLogOpen); syncCalls++; return 0; }
struct IOLock {};
static IOLock *IOLockAlloc() { allocated++; return new IOLock; }
static void IOLockFree(IOLock *p) { freed++; delete p; }
static void IOLockLock(IOLock *) {}
static void IOLockUnlock(IOLock *) {}
static void IOLockSleep(IOLock *, void *, int) { assert(false); }
static void IOLockWakeup(IOLock *, void *, bool) {}
static void *IOMallocZero(unsigned n) { allocated++; return calloc(1,n); }
static void IOFree(void *p, unsigned) { freed++; free(p); }
static void IOLog(const char *, ...) {}
using wait_result_t=int;
using thread_t=void *;
constexpr int KERN_SUCCESS=0, THREAD_UNINT=0;
static void (*pending)(void *, wait_result_t);
static void *pendingArgument;
static int kernel_thread_start(void (*fn)(void *, wait_result_t), void *arg, thread_t *thread) {
    pending=fn; pendingArgument=arg; *thread=reinterpret_cast<void *>(1); return 0;
}
static void thread_deallocate(thread_t) {}
static void thread_terminate(thread_t) {}
static thread_t current_thread() { return nullptr; }
static bool PE_parse_boot_argn(const char *, unsigned *out, unsigned) { *out=mode; return mode != 0; }
static void IOSleep(unsigned);
#include "../platform/sheng/macos26/storage/macoslog_worker.h"
static void IOSleep(unsigned ms) { assert(ms == 2000); __atomic_store_n(&mlStop, 1, __ATOMIC_RELEASE); }
extern "C" unsigned sheng_log_snapshot_copy(void *out, unsigned n) {
    assert(n == 82048); memcpy(out,snapshot,n); return n;
}
extern "C" void run_worker(uint8_t *volume, const uint8_t *h1, const uint8_t *h2,
    const uint8_t *array, const uint8_t *record, unsigned selectedMode, unsigned failure, uint64_t *result) {
    image=volume; primary=h1; backup=h2; entries=array; snapshot=record;
    mode=selectedMode; failWrite=failure; writeCalls=syncCalls=allocated=freed=0; pending=nullptr;
    native_macoslog_state=native_macoslog_error=native_macoslog_phase=0;
    native_macoslog_generation=native_macoslog_snapshots=native_macoslog_busy=native_macoslog_first_lba=0;
    mlStart();
    if (pending) pending(pendingArgument,0);
    mlShutdown();
    assert(!mlRunning && !mlLifecycleLock && !gMacosLogOpen && allocated == freed);
    result[0]=native_macoslog_state; result[1]=native_macoslog_error;
    result[2]=native_macoslog_phase; result[3]=native_macoslog_generation;
    result[4]=native_macoslog_snapshots; result[5]=writeCalls; result[6]=syncCalls;
}
