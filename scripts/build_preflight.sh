#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
task_root=$(cd "$(dirname "$0")/.." && pwd)
probe_name=ShengPreflight
probe_record=preflight-build
probe_options=()
if [[ "${1:-}" = --native-el1 ]]; then
  probe_name=ShengNativeEl1
  probe_record=native-el1-build
  probe_options=(-D SHENG_NATIVE_EL1_PROBE=1)
elif [[ $# -ne 0 ]]; then
  echo 'Usage: build_preflight.sh [--native-el1]' >&2
  exit 2
fi
export SHENG_PROBE_NAME="$probe_name" SHENG_PROBE_RECORD="$probe_record"
export WORKSPACE="$task_root"
export EDK_TOOLS_PATH="$task_root/uefi-sheng/Mu_Basecore/BaseTools"
export PACKAGES_PATH="$task_root:$task_root/uefi-sheng/Mu_Basecore"
export CONF_PATH="$task_root/out/uefi-conf"
export PYTHON_COMMAND=python3
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$task_root/UniXNU-sheng/drivers/ShengPreflight" log -1 --format=%ct)}
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
  "${probe_options[@]}" \
  > "$task_root/out/logs/preflight-build.log" 2>&1
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import struct
base = Path('out/uefi')
name = os.environ['SHENG_PROBE_NAME']
files = list(base.glob(f'RELEASE_*/AARCH64/{name}.efi'))
if len(files) != 1:
    raise SystemExit(f'expected exactly one {name}.efi')
path = files[0]
data = path.read_bytes()
pe = struct.unpack_from('<I', data, 0x3c)[0]
if data[:2] != b'MZ' or data[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', data, pe+4)[0] != 0xaa64:
    raise SystemExit('not an AArch64 PE image')
record = dict(file=path.name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
              hardware_executed=False, note='Standalone UEFI application; not an Android boot image')
sources = ([Path('probes/el1-native/NativeEl1.c'), Path('probes/el1-native/native.S')]
           if name == 'ShengNativeEl1' else [Path('UniXNU-sheng/drivers/ShengPreflight/ShengPreflight.c')])
record['sources_sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
if name == 'ShengPreflight':
    record['source_sha256'] = record['sources_sha256'][str(sources[0])]
record['sources_lock_sha256'] = hashlib.sha256(Path('sources.lock.json').read_bytes()).hexdigest()
Path('out/' + os.environ['SHENG_PROBE_RECORD'] + '.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record))
PY
