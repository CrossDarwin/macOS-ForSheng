#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$task_root"
[[ $(uname -s) == Darwin ]] || { echo 'KDK signature validation requires macOS' >&2; exit 2; }
kdk_config=${1:-config/guest.json}
python3 scripts/fetch_inputs.py --kind kdk --config "$kdk_config"
kdk_filename=$(python3 - "$kdk_config" <<'PYCONFIG'
import json
from pathlib import Path
import sys
name = json.loads(Path(sys.argv[1]).read_text())['kdk']['filename']
if Path(name).name != name or not name.endswith('.dmg'):
    raise SystemExit('Invalid pinned KDK filename')
print(name)
PYCONFIG
)
mkdir -p out/logs
kdk_mount=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/sheng-kdk.XXXXXX")
cleanup() {
  hdiutil detach "$kdk_mount" -quiet || true
  rmdir "$kdk_mount" || true
}
trap cleanup EXIT
hdiutil attach "private/apple/$kdk_filename" -readonly -nobrowse -quiet -mountpoint "$kdk_mount"
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
python3 - "$expanded" "$kdk_config" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
from scripts.check_apple import kdk_kernel_pair
config = json.loads(Path(sys.argv[2]).read_text())
profiles = config.get('kernels')
if profiles is None:
    if config['build'] != '26A428':
        raise SystemExit('KDK configuration has no pinned kernel identities')
    profiles = {'j700ap': {'kdk_name': 'kernel.release.t8140',
                          'uuid': 'F9F468D7-1F50-354A-BECD-6BD6C1C834AD'}}
identities = {}
for board, profile in profiles.items():
    kernel, dwarf = kdk_kernel_pair(Path(sys.argv[1]), profile['kdk_name'])
    expected = profile['uuid'].upper()
    files = {}
    for name, path in (('kernel', kernel), ('dwarf', dwarf)):
        identity = subprocess.check_output(['dwarfdump', '--uuid', str(path)], text=True)
        matches = [line.split()[1].upper() for line in identity.splitlines()
                   if line.startswith('UUID:') and len(line.split()) >= 3
                   and line.split()[2] in ('(arm64)', '(arm64e)')]
        if matches != [expected]:
            raise SystemExit(f'KDK {board} {name} ARM64 UUID differs from its paired IPSW')
        files[name] = str(path.relative_to(sys.argv[1]))
    identities[board] = dict(kernel_uuid=expected, paired_dwarf_uuid_verified=True, files=files)
result = dict(build=config['build'], trusted_apple_package=True, kernels=identities,
              source='Dortania mirror; Apple package signature and paired ARM64 UUIDs verified',
              private_iokit_abi_qualified=False, sheng_hardware_qualified=False)
Path('out/kdk-verification.json').write_text(json.dumps(result, indent=2)+'\n')
print(f"PASS KDK {config['build']} package signature and {len(identities)} paired kernel/DWARF identities")
PY
