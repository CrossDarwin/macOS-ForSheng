// SPDX-License-Identifier: MIT
#pragma once
// Publish the paired BaseSystem as a read-only block device; original APFS authenticates the volume.
#if defined(NATIVE_VERIFIED_BLOCK) && NATIVE_VERIFIED_BLOCK
#error Recovery transport cannot replace the legacy owner verification policy
#endif
#define NATIVE_UFS_RECOVERY_ROOT 1
static bool ufsRecoveryRootIdentity (const char *name, uint64_t bytes, const uint8_t digest[32])
{
  if (!name || !digest) return false;
  static const uint8_t expected[32] = NATIVE_UFS_RECOVERY_DIGEST;
  if (!strcmp (name, "OS") && bytes == NATIVE_UFS_RECOVERY_BYTES)
    return !memcmp (digest, expected, sizeof (expected));
#if defined(NATIVE_UFS_ISC_BYTES)
  static const uint8_t isc[32] = NATIVE_UFS_ISC_DIGEST;
  if (!strcmp (name, "ISC") && bytes == NATIVE_UFS_ISC_BYTES)
    return !memcmp (digest, isc, sizeof (isc));
#endif
  return false;
}
static bool ufsRecoveryRootUuid (const char *name, uint64_t bytes, char out[37])
{
  if (!name || !out) return false;
  static const char expected[] = NATIVE_UFS_RECOVERY_UUID;
  static_assert (sizeof (expected) == 37, "requires the paired recovery UUID");
  if (!strcmp (name, "OS") && bytes == NATIVE_UFS_RECOVERY_BYTES) {
    memcpy (out, expected, sizeof (expected));
    return true;
  }
#if defined(NATIVE_UFS_ISC_BYTES)
  static const char isc[] = NATIVE_UFS_ISC_UUID;
  static_assert (sizeof (isc) == 37, "requires the owned ISC xART UUID");
  if (!strcmp (name, "ISC") && bytes == NATIVE_UFS_ISC_BYTES) {
    memcpy (out, isc, sizeof (isc));
    return true;
  }
#endif
  return false;
}
