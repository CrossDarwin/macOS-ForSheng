// SPDX-License-Identifier: MIT
#include "NativeEl1.h"
#include "layout47.h"
#include <Library/BaseMemoryLib.h>
#include <Library/CacheMaintenanceLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>

EFI_STATUS EFIAPI
UefiMain(EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  UINT64 El, Tcr, Ttbr0, Ttbr1, Mair, Sctlr, SpSel, Sp;
  UINT64 AfterTcr, AfterTtbr0, AfterTtbr1, AfterMair, AfterSctlr;
  sheng47_u64 Result[14] = {0};
  sheng47_u64 *Pages;
  UINTN Progress, Stride, CodeBytes, Attribute;
  UINT64 Status;
  BOOLEAN Restored, Walks, Execute, Permissions;

  (VOID)ImageHandle;
  (VOID)SystemTable;
  gST->ConOut->ClearScreen(gST->ConOut);
  __asm__ volatile("mrs %0,CurrentEL" : "=r"(El));
  Print(L"SHENG-47: EL=%lu - 16K instruction fetch in 47-bit TTBR1\r\n", El >> 2);
  if (El != 4) {
    return ShengProbeFinish(EFI_UNSUPPORTED);
  }
  __asm__ volatile("mrs %0,tcr_el1; mrs %1,ttbr0_el1; mrs %2,ttbr1_el1;"
                   "mrs %3,mair_el1; mrs %4,sctlr_el1; mrs %5,spsel; mov %6,sp"
                   : "=r"(Tcr), "=r"(Ttbr0), "=r"(Ttbr1), "=r"(Mair),
                     "=r"(Sctlr), "=r"(SpSel), "=r"(Sp));
  if (!(Sctlr & 1) || !(Tcr & (1ULL << 23)) || (Tcr & (1ULL << 22)) || SpSel != 1) {
    Print(L"SHENG-47: refused - needs firmware MMU and unused TTBR1\r\n");
    return ShengProbeFinish(EFI_UNSUPPORTED);
  }
  for (Attribute = 0; Attribute < 8; Attribute++) {
    if (((Mair >> (Attribute * 8)) & 255) == 255) {
      break;
    }
  }
  if (Attribute == 8) {
    return ShengProbeFinish(EFI_UNSUPPORTED);
  }
  Pages = AllocateAlignedPages(SHENG47_BYTES / 4096, 16384);
  if (Pages == NULL) {
    return ShengProbeFinish(EFI_OUT_OF_RESOURCES);
  }
  if (!ShengProbeIdentityMapped((UINTN)Pages, SHENG47_BYTES) ||
      !ShengProbeIdentityMapped((UINTN)Result, sizeof(Result)) || Sp < 256 ||
      !ShengProbeIdentityMapped(Sp - 256, 256) ||
      !ShengProbeIdentityMapped((UINTN)ShengEl1Layout47Probe,
           (UINTN)ShengEl1Layout47End - (UINTN)ShengEl1Layout47Probe)) {
    FreeAlignedPages(Pages, SHENG47_BYTES / 4096);
    return ShengProbeFinish(EFI_UNSUPPORTED);
  }
  sheng47_tables(Pages, (unsigned)Attribute);
  CodeBytes = (UINTN)ShengEl1Layout47CodeEnd - (UINTN)ShengEl1Layout47Code;
  if (CodeBytes == 0 || CodeBytes > 16384) {
    FreeAlignedPages(Pages, SHENG47_BYTES / 4096);
    return ShengProbeFinish(EFI_BAD_BUFFER_SIZE);
  }
  CopyMem((UINT8 *)Pages + 6 * 16384, (VOID *)(UINTN)ShengEl1Layout47Code, CodeBytes);
  WriteBackDataCacheRange(Pages, SHENG47_BYTES);
  InvalidateInstructionCacheRange((UINT8 *)Pages + 6 * 16384, CodeBytes);
  if (EFI_ERROR(ShengProbePrepareProgress(&Progress, &Stride))) {
    FreeAlignedPages(Pages, SHENG47_BYTES / 4096);
    return ShengProbeFinish(EFI_UNSUPPORTED);
  }
  Print(L"SHENG-47: code=%lx / %lx data=%lx\r\n",
        (UINT64)SHENG47_LOW, (UINT64)SHENG47_CODE, (UINT64)SHENG47_DATA);
  Print(L"SHENG-47: firmware TTBR0/TG0, MAIR and SCTLR retained\r\n");
  ShengProbePause(L"Press a key to run the 47-bit execution probe");
  Print(L"SHENG-47: probe starting\r\n");
  Status = ShengEl1Layout47Probe(Pages, Result, sheng47_tcr(Tcr), Progress, Stride);
  __asm__ volatile("mrs %0,tcr_el1; mrs %1,ttbr0_el1; mrs %2,ttbr1_el1;"
                   "mrs %3,mair_el1; mrs %4,sctlr_el1"
                   : "=r"(AfterTcr), "=r"(AfterTtbr0), "=r"(AfterTtbr1),
                     "=r"(AfterMair), "=r"(AfterSctlr));
  Restored = Tcr == AfterTcr && Ttbr0 == AfterTtbr0 && Ttbr1 == AfterTtbr1 &&
             Mair == AfterMair && Sctlr == AfterSctlr;
  Walks = !(Result[0] & 1) && !(Result[1] & 1) && !(Result[2] & 1) &&
          (Result[0] & 0x0000fffffffff000ULL) == (UINTN)Pages + 6 * 16384 &&
          (Result[1] & 0x0000fffffffff000ULL) == (UINTN)Pages + 6 * 16384 &&
          (Result[2] & 0x0000fffffffff000ULL) == (UINTN)Pages + 7 * 16384;
  Execute = Result[4] == SHENG47_LOW && Result[5] == SHENG47_CODE &&
            Result[6] == 0x4747 && Result[7] == 0x5757 && Result[8] == 0x5757;
  Permissions = (Result[3] & 1) && (Result[9] & 1);
  Print(L"SHENG-47: walks=%s execute=%s controls=%s firmware-restored=%s\r\n",
        Walks ? L"PASS" : L"FAIL", Execute ? L"PASS" : L"FAIL",
        Permissions ? L"PASS" : L"FAIL", Restored ? L"PASS" : L"FAIL");
  Print(L"SHENG-47: PC low=%lx high=%lx data=%lx\r\n", Result[4], Result[5], Result[8]);
  if (Status) {
    Print(L"SHENG-47: trap stage=%lu ESR=%lx FAR=%lx ELR=%lx\r\n",
          Result[13], Result[10], Result[11], Result[12]);
  }
  FreeAlignedPages(Pages, SHENG47_BYTES / 4096);
  Print(L"SHENG-47: standalone EL1 execution; XNU and arm64e userspace not started\r\n");
  return ShengProbeFinish(!Status && Walks && Execute && Permissions && Restored ?
                          EFI_SUCCESS : EFI_DEVICE_ERROR);
}
