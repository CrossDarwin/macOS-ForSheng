// SPDX-License-Identifier: MIT
#define NATIVE_MACOSLOG 1
#define main original_commands_main
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wreturn-type"
#include "../UniXNU/drivers/NativeUfs/tests/RootCommands.cpp"
#pragma GCC diagnostic pop
#undef main

int main() {
    reset();
    gMacosLogOpen = false;
    assert(hostMacosLogReady() == kIOReturnSuccess);
    assert(device[kUcdOffset+2] == 4 && device[kUcdOffset+16] == 0);
    std::array<uint8_t, 21*4096> data{};
    assert(hostWrite4k(4, 448600, 1, data.data()) == kIOReturnBadArgument);
    assert(!hostMacosLogOpen(448512, 511));
    assert(!hostMacosLogOpen(464385, 511));
    assert(!hostMacosLogOpen(448600, 512));
    assert(hostMacosLogOpen(448600, 511));
    assert(!hostMacosLogOpen(448600, 511));
    assert(hostWrite4k(4, 448601, 21, data.data()) == kIOReturnSuccess);
    const uint8_t *cmd = device.data()+kUcdOffset;
    assert(cmd[2] == 4 && cmd[16] == 0x2a);
    assert(loadBe32(cmd+18) == 448601);
    assert(hostWrite4k(4, 449110, 1, data.data()) == kIOReturnSuccess);
    auto previous = writes;
    for (uint8_t lun : {0, 1, 2, 3, 5, 6})
        assert(hostWrite4k(lun, 448600, 1, data.data()) == kIOReturnBadArgument);
    for (uint64_t at : std::array<uint64_t, 5>{1, 448599, 449111, 464895, UINT64_MAX})
        assert(hostWrite4k(4, at, 1, data.data()) == kIOReturnBadArgument);
    assert(hostWrite4k(4, 449110, 2, data.data()) == kIOReturnBadArgument);
    assert(writes == previous);
    assert(hostMacosLogSync() == kIOReturnSuccess);
    assert(cmd[2] == 4 && cmd[16] == 0x35);
    assert(hostStoreOpen(100, 2));
    assert(hostWrite4k(0, 100, 1, data.data()) == kIOReturnSuccess);
    assert(cmd[2] == 0);
    reset(Fault::CheckCondition);
    assert(hostMacosLogReady() == kIOReturnNotReady && now == 4000 && !gHost.poisoned);
    reset(Fault::Timeout);
    assert(hostWrite4k(4, 448600, 1, data.data()) != kIOReturnSuccess);
    assertQuarantined();
    puts("PASS: dedicated LUN4 data window, immutable guard exclusion, sync LUN and existing LUN0 policy");
}
