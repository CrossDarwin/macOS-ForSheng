#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$task_root"
[[ $(uname -s) == Darwin ]] || { echo 'KDK signature validation requires macOS' >&2; exit 2; }
python3 scripts/fetch_inputs.py --kind kdk
mkdir -p out/logs
kdk_mount=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/sheng-kdk.XXXXXX")
cleanup() {
  hdiutil detach "$kdk_mount" -quiet || true
  rmdir "$kdk_mount" || true
}
trap cleanup EXIT
hdiutil attach private/apple/Kernel_Debug_Kit_27.0_build_26A428.dmg -readonly -nobrowse -quiet -mountpoint "$kdk_mount"
pkgutil --check-signature "$kdk_mount/KernelDebugKit.pkg" > out/logs/kdk-signature.log
python3 - <<'PY'
from pathlib import Path
text = Path('out/logs/kdk-signature.log').read_text()
if 'signed by a certificate trusted by' not in text or 'Apple Inc.' not in text:
    raise SystemExit('KDK package does not have the expected trusted Apple signer')
print('PASS trusted Apple KDK package signature')
PY
expanded="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/sheng-kdk-expanded-${GITHUB_RUN_ID:-$$}"
pkgutil --expand-full "$kdk_mount/KernelDebugKit.pkg" "$expanded"
python3 - "$expanded" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
kernels = list(Path(sys.argv[1]).rglob('kernel.release.t8140'))
if len(kernels) != 1:
    raise SystemExit('KDK must contain exactly one T8140 release kernel')
identity = subprocess.check_output(['dwarfdump', '--uuid', str(kernels[0])], text=True)
expected = 'F9F468D7-1F50-354A-BECD-6BD6C1C834AD'
if expected not in identity.upper():
    raise SystemExit('KDK kernel UUID differs from the pinned J700 kernel')
result = dict(build='26A428', trusted_apple_package=True, kernel_uuid=expected,
              source='Dortania mirror; package signature and T8140 UUID verified',
              private_iokit_abi_qualified=False, sheng_hardware_qualified=False)
Path('out/kdk-verification.json').write_text(json.dumps(result, indent=2)+'\n')
print('PASS KDK T8140 kernel UUID matches the audited J700 input')
PY
