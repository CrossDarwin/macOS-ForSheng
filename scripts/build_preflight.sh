#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
export WORKSPACE="$task_root"
export EDK_TOOLS_PATH="$task_root/uefi-sheng/Mu_Basecore/BaseTools"
export PACKAGES_PATH="$task_root:$task_root/uefi-sheng/Mu_Basecore"
export CONF_PATH="$task_root/out/uefi-conf"
export PYTHON_COMMAND=python3
export PATH="$EDK_TOOLS_PATH/BinWrappers/PosixLike:$EDK_TOOLS_PATH/Source/C/bin:$PATH"
mkdir -p "$CONF_PATH" "$task_root/out/logs"
for config in target tools_def build_rule; do
  if [[ ! -f "$CONF_PATH/$config.txt" ]]; then
    cp "$EDK_TOOLS_PATH/Conf/$config.template" "$CONF_PATH/$config.txt"
  fi
done
make -C "$EDK_TOOLS_PATH" -j "${JOBS:-4}" > "$task_root/out/logs/basetools.log" 2>&1
cd "$task_root"
build -p ci/preflight.dsc -a AARCH64 -b RELEASE -t "${TOOL_CHAIN_TAG:-CLANGPDB}" -n "${JOBS:-4}" \
  > "$task_root/out/logs/preflight-build.log" 2>&1
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import struct
base = Path('out/uefi')
files = list(base.glob('RELEASE_*/AARCH64/ShengPreflight.efi'))
if len(files) != 1:
    raise SystemExit('expected exactly one ShengPreflight.efi')
path = files[0]
data = path.read_bytes()
pe = struct.unpack_from('<I', data, 0x3c)[0]
if data[:2] != b'MZ' or data[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', data, pe+4)[0] != 0xaa64:
    raise SystemExit('not an AArch64 PE image')
record = dict(file=path.name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
              hardware_executed=False, note='Standalone UEFI application; not an Android boot image')
Path('out/preflight-build.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record))
PY
