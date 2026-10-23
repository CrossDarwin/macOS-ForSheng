// SPDX-License-Identifier: MIT
#ifndef SHENG_NATIVE_EL1_H
#define SHENG_NATIVE_EL1_H
#include <Uefi.h>
BOOLEAN ShengProbePause(CONST CHAR16 *Message);
EFI_STATUS ShengProbeFinish(EFI_STATUS Result);
BOOLEAN ShengProbeIdentityMapped(UINTN Start, UINTN Bytes);
EFI_STATUS ShengProbePrepareProgress(UINTN *Progress, UINTN *Stride);
EFI_STATUS EFIAPI ShengGranuleMain(EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable);
#endif
