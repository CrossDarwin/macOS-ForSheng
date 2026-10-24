// SPDX-License-Identifier: MIT
#pragma once
// 配套BaseSystem只作为只读块设备发布，原版APFS负责卷认证
#if defined(NATIVE_VERIFIED_BLOCK) && NATIVE_VERIFIED_BLOCK
#error Recovery transport cannot replace the legacy owner verification policy
#endif
#define NATIVE_UFS_RECOVERY_ROOT 1
static bool ufsRecoveryRootIdentity (const char *name, uint64_t bytes, const uint8_t digest[32])
{
  if (!name || !digest || strcmp (name, "OS") || bytes != NATIVE_UFS_RECOVERY_BYTES) return false;
  static const uint8_t expected[32] = NATIVE_UFS_RECOVERY_DIGEST;
  return !memcmp (digest, expected, sizeof (expected));
}
static bool ufsRecoveryRootUuid (const char *name, uint64_t bytes, char out[37])
{
  if (!name || !out || strcmp (name, "OS") || bytes != NATIVE_UFS_RECOVERY_BYTES) return false;
  static const char expected[] = NATIVE_UFS_RECOVERY_UUID;
  static_assert (sizeof (expected) == 37, "requires the paired recovery UUID");
  memcpy (out, expected, sizeof (expected));
  return true;
}
