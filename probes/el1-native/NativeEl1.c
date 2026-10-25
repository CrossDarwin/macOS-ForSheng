// SPDX-License-Identifier: MIT
#include "NativeEl1.h"
#include <Library/CacheMaintenanceLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Protocol/SimpleTextIn.h>
#include <Protocol/GraphicsOutput.h>

extern UINT64 ShengEl1GranuleProbe (UINT64 *Table, UINT64 *Output, UINT64 Tcr,
                                   UINTN Progress, UINTN Stride, UINT64 Leaf);
extern VOID ShengEl1GranuleProbeEnd (VOID);
extern UINT64 ShengEl1PauthProbe (UINT64 *Output);

BOOLEAN
ShengProbePause (CONST CHAR16 *Message)
{
  EFI_INPUT_KEY Key;
  EFI_HANDLE *Handles;
  EFI_SIMPLE_TEXT_INPUT_PROTOCOL *Inputs[33];
  EFI_SIMPLE_TEXT_INPUT_PROTOCOL *Input;
  UINTN Count;
  UINTN Used;
  UINTN Index;
  UINTN Other;
  BOOLEAN Duplicate;

  Used = 1;
  Inputs[0] = gST->ConIn;
  Handles = NULL;
  Count = 0;
  if (!EFI_ERROR (gBS->LocateHandleBuffer (ByProtocol, &gEfiSimpleTextInProtocolGuid,
                                          NULL, &Count, &Handles))) {
    for (Index = 0; Index < Count && Used < 33; Index++) {
      if (EFI_ERROR (gBS->HandleProtocol (Handles[Index], &gEfiSimpleTextInProtocolGuid,
                                         (VOID **) &Input))) {
        continue;
      }
      Duplicate = FALSE;
      for (Other = 0; Other < Used; Other++) {
        if (Inputs[Other] == Input) {
          Duplicate = TRUE;
        }
      }
      if (!Duplicate) {
        Inputs[Used++] = Input;
      }
    }
    FreePool (Handles);
  }
  Print (L"SHENG-EL1: input devices=%lu\r\n", (UINT64) Used);
  Print (L"%s\r\n", Message);
  for (Index = 0; Index < Used; Index++) {
    while (!EFI_ERROR (Inputs[Index]->ReadKeyStroke (Inputs[Index], &Key))) {
    }
  }
  for (;;) {
    for (Index = 0; Index < Used; Index++) {
      if (!EFI_ERROR (Inputs[Index]->ReadKeyStroke (Inputs[Index], &Key))) {
        Print (L"SHENG-EL1: key received source=%lu scan=%u char=%u\r\n",
               (UINT64) Index, Key.ScanCode, Key.UnicodeChar);
        return TRUE;
      }
    }
    gBS->Stall (20000);
  }
}

EFI_STATUS
ShengProbeFinish (EFI_STATUS Result)
{
  Print (L"SHENG-EL1: status=%r\r\n", Result);
  ShengProbePause (L"Press a key to return to the boot menu");
  return Result;
}

BOOLEAN
ShengProbeIdentityMapped (UINTN Start, UINTN Bytes)
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

// Draw labels using firmware mappings; assembly only fills green stage cells without firmware calls.
EFI_STATUS
ShengProbePrepareProgress (UINTN *Progress, UINTN *Stride)
{
  STATIC CONST UINT8 Font[16][7] = {
    {14,17,19,21,25,17,14}, {4,12,4,4,4,4,14},
    {14,17,1,2,4,8,31}, {30,1,1,14,1,1,30},
    {2,6,10,18,31,2,2}, {31,16,16,30,1,1,30},
    {14,16,16,30,17,17,14}, {31,1,2,4,8,8,8},
    {14,17,17,14,17,17,14}, {14,17,17,15,1,1,14},
    {14,17,17,31,17,17,17}, {30,17,17,30,17,17,30},
    {14,17,16,16,16,17,14}, {30,17,17,17,17,17,30},
    {31,16,16,30,16,16,31}, {31,16,16,30,16,16,16}
  };
  EFI_GRAPHICS_OUTPUT_PROTOCOL *Gop;
  EFI_GRAPHICS_OUTPUT_MODE_INFORMATION *Info;
  EFI_STATUS Status;
  UINTN Start, Span, X, Y, Digit, Row, Col, Dx, Dy;
  volatile UINT32 *Pixels;

  Status = gBS->LocateProtocol (&gEfiGraphicsOutputProtocolGuid, NULL, (VOID **) &Gop);
  if (EFI_ERROR (Status) || Gop->Mode == NULL || Gop->Mode->Info == NULL) {
    return EFI_UNSUPPORTED;
  }
  Info = Gop->Mode->Info;
  if ((Info->PixelFormat != PixelRedGreenBlueReserved8BitPerColor &&
       Info->PixelFormat != PixelBlueGreenRedReserved8BitPerColor) ||
      Info->HorizontalResolution < 512 || Info->VerticalResolution < 128 ||
      Info->PixelsPerScanLine < Info->HorizontalResolution) {
    return EFI_UNSUPPORTED;
  }
  *Stride = (UINTN) Info->PixelsPerScanLine * 4;
  X = (Info->HorizontalResolution - 512) / 2;
  Y = Info->VerticalResolution / 2;
  Span = 63 * *Stride + 512 * 4;
  if (Y * *Stride + X * 4 + Span > Gop->Mode->FrameBufferSize) {
    return EFI_UNSUPPORTED;
  }
  Start = (UINTN) Gop->Mode->FrameBufferBase + Y * *Stride + X * 4;
  if (!ShengProbeIdentityMapped (Start, Span)) {
    return EFI_UNSUPPORTED;
  }
  for (Row = 0; Row < 64; Row++) {
    Pixels = (volatile UINT32 *) (Start + Row * *Stride);
    for (Col = 0; Col < 512; Col++) {
      Pixels[Col] = 0;
    }
  }
  for (Digit = 0; Digit < 16; Digit++) {
    for (Row = 0; Row < 7; Row++) {
      for (Col = 0; Col < 5; Col++) {
        if (!(Font[Digit][Row] & (1U << (4 - Col)))) {
          continue;
        }
        for (Dy = 0; Dy < 4; Dy++) {
          Pixels = (volatile UINT32 *) (Start + (Row * 4 + Dy) * *Stride);
          for (Dx = 0; Dx < 4; Dx++) {
            Pixels[Digit * 32 + Col * 4 + Dx] = 0x00ffffff;
          }
        }
      }
    }
  }
  WriteBackDataCacheRange ((VOID *) Start, Span);
  *Progress = Start + 36 * *Stride;
  Print (L"SHENG-EL1: checkpoints 0-F, green means executed\r\n");
  return EFI_SUCCESS;
}

EFI_STATUS EFIAPI
ShengGranuleMain (EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  UINT64 El, Mmfr0, Isar1, Isar2, Sp, Sctlr, SpSel;
  UINT64 BeforeTcr, BeforeTtbr, BeforeMair, AfterTcr, AfterTtbr, AfterMair, AfterSctlr;
  UINT64 BeforeTtbr1, AfterTtbr1;
  UINT64 *Table;
  UINT64 Result[8] = { 0 };
  UINT64 ProbeStatus;
  UINT64 Signatures[10] = { 0 };
  UINT64 PauthFlags = 0;
  UINT64 Tcr, Leaf;
  UINTN Index;
  UINTN Progress, Stride;
  BOOLEAN Restored;
  BOOLEAN Granule;

  (VOID) ImageHandle;
  (VOID) SystemTable;
  gST->ConOut->ClearScreen (gST->ConOut);
  __asm__ volatile ("mrs %0, CurrentEL" : "=r" (El));
  Print (L"SHENG-EL1: application entered, EL=%lu\r\n", El >> 2);
  if (El != 4) {
    Print (L"SHENG-EL1: requires EL1, CurrentEL=0x%lx\r\n", El);
    return ShengProbeFinish (EFI_UNSUPPORTED);
  }
  __asm__ volatile ("mrs %0, id_aa64mmfr0_el1" : "=r" (Mmfr0));
  __asm__ volatile ("mrs %0, id_aa64isar1_el1" : "=r" (Isar1));
  __asm__ volatile ("mrs %0, id_aa64isar2_el1" : "=r" (Isar2));
  __asm__ volatile ("mrs %0, sctlr_el1; mov %1, sp" : "=r" (Sctlr), "=r" (Sp));
  Print (L"SHENG-EL1: SCTLR=%lx SP=%lx PC=%lx\r\n", Sctlr, Sp, (UINT64) (UINTN) ShengEl1GranuleProbe);
  if (!(Sctlr & 1)) {
    Print (L"SHENG-EL1: refused - firmware MMU is off\r\n");
    return ShengProbeFinish (EFI_UNSUPPORTED);
  }
  __asm__ volatile ("mrs %0, tcr_el1; mrs %1, ttbr0_el1; mrs %2, mair_el1;"
                    "mrs %3, ttbr1_el1; mrs %4, spsel"
                    : "=r" (BeforeTcr), "=r" (BeforeTtbr), "=r" (BeforeMair),
                      "=r" (BeforeTtbr1), "=r" (SpSel));
  if (!(BeforeTcr & (1ULL << 23)) || (BeforeTcr & (1ULL << 22)) || SpSel != 1) {
    Print (L"SHENG-EL1: refused - requires unused TTBR1, TTBR0 ASID and SP_EL1\r\n");
    return ShengProbeFinish (EFI_UNSUPPORTED);
  }
  for (Index = 0; Index < 8; Index++) {
    if (((BeforeMair >> (Index * 8)) & 255) == 255) {
      break;
    }
  }
  if (Index == 8) {
    Print (L"SHENG-EL1: refused - firmware lacks normal WB MAIR attribute\r\n");
    return ShengProbeFinish (EFI_UNSUPPORTED);
  }
  Leaf = 0x701 | ((UINT64) Index << 2);
  Table = AllocateAlignedPages (4, 16384);
  if (Table == NULL) {
    return ShengProbeFinish (EFI_OUT_OF_RESOURCES);
  }
  if (!ShengProbeIdentityMapped ((UINTN) ShengEl1GranuleProbe,
                       (UINTN) ShengEl1GranuleProbeEnd - (UINTN) ShengEl1GranuleProbe) ||
      !ShengProbeIdentityMapped ((UINTN) Table, 16384) ||
      !ShengProbeIdentityMapped ((UINTN) Result, sizeof (Result)) ||
      Sp < 256 || !ShengProbeIdentityMapped (Sp - 256, 256)) {
    Print (L"SHENG-EL1: refused - execution or buffers lack the required identity mapping\r\n");
    FreeAlignedPages (Table, 4);
    return ShengProbeFinish (EFI_UNSUPPORTED);
  }
  for (Index = 0; Index < 2048; Index++) {
    Table[Index] = 0;
  }
  WriteBackDataCacheRange (Table, 16384);
  // Change only the disabled high-address window; preserve firmware TTBR0, TG0, and IPS.
  Tcr = BeforeTcr & ~((3ULL << 30) | (3ULL << 28) | (3ULL << 26) |
                      (3ULL << 24) | (1ULL << 23) | (63ULL << 16));
  Tcr |= (2ULL << 30) | (3ULL << 28) | (1ULL << 26) | (1ULL << 24) | (28ULL << 16);
  Print (L"SHENG-EL1: firmware TCR=%lx TTBR0=%lx MAIR=%lx\r\n",
         BeforeTcr, BeforeTtbr, BeforeMair);
  if (EFI_ERROR (ShengProbePrepareProgress (&Progress, &Stride))) {
    Print (L"SHENG-EL1: refused - framebuffer checkpoints unavailable\r\n");
    FreeAlignedPages (Table, 4);
    return ShengProbeFinish (EFI_UNSUPPORTED);
  }
  Print (L"SHENG-EL1: TTBR1 scratch walk, firmware MMU stays on, MMFR0=0x%lx\r\n", Mmfr0);
  if (!ShengProbePause (L"Press a key to run the MMU probe")) {
    FreeAlignedPages (Table, 4);
    return ShengProbeFinish (EFI_DEVICE_ERROR);
  }
  Print (L"SHENG-EL1: MMU probe starting\r\n");
  gBS->Stall (200000);
  ProbeStatus = ShengEl1GranuleProbe (Table, Result, Tcr, Progress, Stride, Leaf);
  __asm__ volatile ("mrs %0, tcr_el1; mrs %1, ttbr0_el1; mrs %2, mair_el1; mrs %3, sctlr_el1"
                    : "=r" (AfterTcr), "=r" (AfterTtbr), "=r" (AfterMair), "=r" (AfterSctlr));
  __asm__ volatile ("mrs %0, ttbr1_el1" : "=r" (AfterTtbr1));
  Restored = BeforeTcr == AfterTcr && BeforeTtbr == AfterTtbr &&
             BeforeTtbr1 == AfterTtbr1 && BeforeMair == AfterMair && Sctlr == AfterSctlr;
  Granule = !(Result[0] & 1) && (Result[0] & 0x0000fffffffff000ULL) == 0x1000 &&
            (Result[1] & 1) && (Result[2] & 1) && !(Result[3] & 1) &&
            (Result[3] & 0x0000fffffffff000ULL) == 0x4001000;
  Print (L"SHENG-EL1: PAR A=%lx B=%lx C=%lx D=%lx\r\n", Result[0], Result[1], Result[2], Result[3]);
  Print (L"SHENG-EL1: granule16=%s firmware-restored=%s\r\n",
         Granule ? L"PASS" : L"FAIL", Restored ? L"PASS" : L"FAIL");
  FreeAlignedPages (Table, 4);
  if (ProbeStatus) {
    Print (L"SHENG-EL1: trap stage=%lu ESR=%lx FAR=%lx ELR=%lx\r\n",
           Result[7], Result[4], Result[5], Result[6]);
  }
  if (!Restored || ProbeStatus) {
    return ShengProbeFinish (EFI_DEVICE_ERROR);
  }
  if (((Isar1 >> 4) & 255) != 0 &&
      (((Isar1 >> 24) & 255) != 0 || ((Isar2 >> 8) & 15) != 0)) {
    if (!ShengProbePause (L"Press a key to run the PAC probe")) {
      return ShengProbeFinish (EFI_DEVICE_ERROR);
    }
    Print (L"SHENG-EL1: PAC probe starting\r\n");
    gBS->Stall (200000);
    PauthFlags = ShengEl1PauthProbe (Signatures);
    Print (L"SHENG-EL1: PAC bank-switch=%s flags=0x%lx expected=0x7fff\r\n",
           PauthFlags == 0x7fff ? L"PASS" : L"FAIL", PauthFlags);
  } else {
    Print (L"SHENG-EL1: PAC skipped - address/generic authentication not advertised\r\n");
  }
  Print (L"SHENG-EL1: boot CPU only; 47-bit layout and XNU task switching remain pending\r\n");
  return ShengProbeFinish (Granule && PauthFlags == 0x7fff ? EFI_SUCCESS : EFI_UNSUPPORTED);
}
