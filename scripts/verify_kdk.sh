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
from scripts.check_apple import trusted_kdk_signature
text = Path('out/logs/kdk-signature.log').read_text()
if not trusted_kdk_signature(text):
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
from scripts.check_apple import kdk_kernel_pair
kernel, dwarf = kdk_kernel_pair(Path(sys.argv[1]))
expected = 'F9F468D7-1F50-354A-BECD-6BD6C1C834AD'
identities = {}
for name, path in (('kernel', kernel), ('dwarf', dwarf)):
    identity = subprocess.check_output(['dwarfdump', '--uuid', str(path)], text=True)
    if expected not in identity.upper():
        raise SystemExit(f'KDK {name} UUID differs from the pinned J700 kernel')
    identities[name] = str(path.relative_to(sys.argv[1]))
result = dict(build='26A428', trusted_apple_package=True, kernel_uuid=expected,
              paired_dwarf_uuid_verified=True, files=identities,
              source='Dortania mirror; package signature and T8140 UUID verified',
              private_iokit_abi_qualified=False, sheng_hardware_qualified=False)
Path('out/kdk-verification.json').write_text(json.dumps(result, indent=2)+'\n')
print('PASS KDK T8140 kernel UUID matches the audited J700 input')
PY
