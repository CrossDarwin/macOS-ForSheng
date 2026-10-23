// SPDX-License-Identifier: MIT
#include <Uefi.h>
#include <Library/CacheMaintenanceLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>

extern UINT64 ShengEl1GranuleProbe (UINT64 *Table, UINT64 *Output, UINT64 Tcr);
extern VOID ShengEl1GranuleProbeEnd (VOID);
extern UINT64 ShengEl1PauthProbe (UINT64 *Output);

STATIC EFI_STATUS
Finish (EFI_STATUS Result)
{
  EFI_INPUT_KEY Key;
  UINTN Event;

  Print (L"SHENG-EL1: status=%r\r\nPress a key to return to the boot menu\r\n", Result);
  while (!EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
  }
  do {
    if (EFI_ERROR (gBS->WaitForEvent (1, &gST->ConIn->WaitForKey, &Event))) {
      return EFI_DEVICE_ERROR;
    }
  } while (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key)));
  return Result;
}

STATIC BOOLEAN
IdentityMapped (UINTN Start, UINTN Bytes)
{
  UINT64 SavedPar;
  UINT64 Par;
  UINTN Address;
  UINTN End;

  if (Start < 0x80000000ULL || Bytes == 0 || Start >= (1ULL << 36) ||
      Bytes > (1ULL << 36) - Start) {
    Print (L"SHENG-EL1: address outside probe window VA=%lx bytes=%lu\r\n", (UINT64) Start, (UINT64) Bytes);
    return FALSE;
  }
  End = Start + Bytes - 1;
  __asm__ volatile ("mrs %0, par_el1" : "=r" (SavedPar));
  Address = Start & ~0xfffULL;
  do {
    __asm__ volatile ("at s1e1r, %1; isb; mrs %0, par_el1" : "=r" (Par) : "r" (Address) : "memory");
    if ((Par & 1) || (Par & 0x0000fffffffff000ULL) != Address) {
      __asm__ volatile ("msr par_el1, %0" :: "r" (SavedPar));
      Print (L"SHENG-EL1: identity refused VA=%lx PAR=%lx\r\n", (UINT64) Address, Par);
      return FALSE;
    }
    Address += 4096;
  } while (Address <= End);
  __asm__ volatile ("msr par_el1, %0" :: "r" (SavedPar));
  return TRUE;
}

EFI_STATUS EFIAPI
UefiMain (EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  UINT64 El, Mmfr0, Isar1, Isar2, Sp, Sctlr;
  UINT64 BeforeTcr, BeforeTtbr, BeforeMair, AfterTcr, AfterTtbr, AfterMair, AfterSctlr;
  UINT64 *Table;
  UINT64 Result[4] = { 0 };
  UINT64 Signatures[10] = { 0 };
  UINT64 PauthFlags = 0;
  UINT64 Tcr;
  UINTN Index;
  BOOLEAN Restored;
  BOOLEAN Granule;

  (VOID) ImageHandle;
  (VOID) SystemTable;
  gST->ConOut->ClearScreen (gST->ConOut);
  __asm__ volatile ("mrs %0, CurrentEL" : "=r" (El));
  Print (L"SHENG-EL1: application entered, EL=%lu\r\n", El >> 2);
  if (El != 4) {
    Print (L"SHENG-EL1: requires EL1, CurrentEL=0x%lx\r\n", El);
    return Finish (EFI_UNSUPPORTED);
  }
  __asm__ volatile ("mrs %0, id_aa64mmfr0_el1" : "=r" (Mmfr0));
  __asm__ volatile ("mrs %0, id_aa64isar1_el1" : "=r" (Isar1));
  __asm__ volatile ("mrs %0, id_aa64isar2_el1" : "=r" (Isar2));
  __asm__ volatile ("mrs %0, sctlr_el1; mov %1, sp" : "=r" (Sctlr), "=r" (Sp));
  Print (L"SHENG-EL1: SCTLR=%lx SP=%lx PC=%lx\r\n", Sctlr, Sp, (UINT64) (UINTN) ShengEl1GranuleProbe);
  if (!(Sctlr & 1)) {
    Print (L"SHENG-EL1: refused - firmware MMU is off\r\n");
    return Finish (EFI_UNSUPPORTED);
  }
  Table = AllocateAlignedPages (4, 16384);
  if (Table == NULL) {
    return Finish (EFI_OUT_OF_RESOURCES);
  }
  if (!IdentityMapped ((UINTN) ShengEl1GranuleProbe,
                       (UINTN) ShengEl1GranuleProbeEnd - (UINTN) ShengEl1GranuleProbe) ||
      !IdentityMapped ((UINTN) Table, 16384) ||
      !IdentityMapped ((UINTN) Result, sizeof (Result)) ||
      Sp < 256 || !IdentityMapped (Sp - 256, 256)) {
    Print (L"SHENG-EL1: refused - execution or buffers lack the required identity mapping\r\n");
    FreeAlignedPages (Table, 4);
    return Finish (EFI_UNSUPPORTED);
  }
  // 两种硬件解释均覆盖执行区，低地址仅作为AT的区分样本
  for (Index = 0; Index < 2048; Index++) {
    Table[Index] = Index < 2 ? 0 :
      (((UINT64) Index << (Index < 64 ? 30 : 25)) | 0x701);
  }
  WriteBackDataCacheRange (Table, 16384);
  Tcr = 28 | (1ULL << 8) | (1ULL << 10) | (3ULL << 12) | (1ULL << 23) |
        ((Mmfr0 & 15) > 5 ? 5ULL << 32 : (Mmfr0 & 15) << 32);
  __asm__ volatile ("mrs %0, tcr_el1; mrs %1, ttbr0_el1; mrs %2, mair_el1"
                    : "=r" (BeforeTcr), "=r" (BeforeTtbr), "=r" (BeforeMair));
  Print (L"SHENG-EL1: testing page walks at EL1, MMFR0=0x%lx\r\n", Mmfr0);
  ShengEl1GranuleProbe (Table, Result, Tcr);
  __asm__ volatile ("mrs %0, tcr_el1; mrs %1, ttbr0_el1; mrs %2, mair_el1; mrs %3, sctlr_el1"
                    : "=r" (AfterTcr), "=r" (AfterTtbr), "=r" (AfterMair), "=r" (AfterSctlr));
  Restored = BeforeTcr == AfterTcr && BeforeTtbr == AfterTtbr &&
             BeforeMair == AfterMair && Sctlr == AfterSctlr;
  Granule = !(Result[0] & 1) && (Result[0] & 0x0000fffffffff000ULL) == 0x1000 &&
            (Result[1] & 1) && (Result[2] & 1) && !(Result[3] & 1) &&
            (Result[3] & 0x0000fffffffff000ULL) == 0x4001000;
  Print (L"SHENG-EL1: PAR A=%lx B=%lx C=%lx D=%lx\r\n", Result[0], Result[1], Result[2], Result[3]);
  Print (L"SHENG-EL1: granule16=%s firmware-restored=%s\r\n",
         Granule ? L"PASS" : L"FAIL", Restored ? L"PASS" : L"FAIL");
  FreeAlignedPages (Table, 4);
  if (!Restored) {
    return Finish (EFI_DEVICE_ERROR);
  }
  if (((Isar1 >> 4) & 255) != 0 &&
      (((Isar1 >> 24) & 255) != 0 || ((Isar2 >> 8) & 15) != 0)) {
    PauthFlags = ShengEl1PauthProbe (Signatures);
    Print (L"SHENG-EL1: PAC bank-switch=%s flags=0x%lx expected=0x7fff\r\n",
           PauthFlags == 0x7fff ? L"PASS" : L"FAIL", PauthFlags);
  } else {
    Print (L"SHENG-EL1: PAC skipped - address/generic authentication not advertised\r\n");
  }
  Print (L"SHENG-EL1: boot CPU only; 47-bit layout and XNU task switching remain pending\r\n");
  return Finish (Granule && PauthFlags == 0x7fff ? EFI_SUCCESS : EFI_UNSUPPORTED);
}
