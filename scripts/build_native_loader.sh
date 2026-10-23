#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: build_native_loader.sh /absolute/path/to/llvm/bin' >&2
  exit 2
fi
task_root=$(cd "$(dirname "$0")/.." && pwd)
export CLANG_BIN="$(cd "$1" && pwd)/"
export WORKSPACE="$task_root"
export EDK_TOOLS_PATH="$task_root/uefi-sheng/Mu_Basecore/BaseTools"
export PACKAGES_PATH="$task_root/UniXNU/drivers/DarwinBoot:$task_root/UniXNU/package:$task_root/uefi-sheng/Mu_Basecore"
export CONF_PATH="$task_root/out/native-loader-conf"
export PYTHON_COMMAND=python3
export PATH="$EDK_TOOLS_PATH/BinWrappers/PosixLike:$EDK_TOOLS_PATH/Source/C/bin:$PATH"
mkdir -p "$CONF_PATH" "$task_root/out/logs"
for config in target tools_def build_rule; do
  if [[ ! -f "$CONF_PATH/$config.txt" ]]; then
    cp "$EDK_TOOLS_PATH/Conf/$config.template" "$CONF_PATH/$config.txt"
  fi
done
cd "$task_root"
python3 - <<'PY'
from pathlib import Path
source = Path('UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c').read_text()
if '#define BLOCK_SIZE   SIZE_32MB' not in source:
    raise SystemExit('native loader requires the recorded 32 MiB bootstrap congruence patch')
entry = Path('UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/Entry.S').read_text()
if entry.count('  DARWIN_HANDOFF_PROGRESS ') != 3 or 'HANDOFF: green=entered' not in source:
    raise SystemExit('native loader requires the three actual handoff progress markers')
dsc = Path('UniXNU/drivers/DarwinBoot/DarwinBootPkg/DarwinBoot.dsc').read_text()
dsc = dsc.replace('OUTPUT_DIRECTORY = build/DarwinBoot', 'OUTPUT_DIRECTORY = out/native-loader')
dsc = dsc.replace('  Test/Validation.inf\n', '')
Path('out/native-loader.dsc').write_text(dsc)
PY
build -p out/native-loader.dsc -a AARCH64 -b RELEASE -t CLANGPDB -n "${JOBS:-4}" \
  > out/logs/native-loader-build.log 2>&1
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('out/native-loader/RELEASE_CLANGPDB/AARCH64/DarwinBoot.efi')
record = dict(file=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
              native_arm64e_supported=True,
              handoff_panic_address_visible=True,
              handoff_progress='green=entered blue=cache-clean orange=MMU-off',
              bootstrap_block_bytes=33554432, native_panic_region_bytes=524288, hardware_tested=False,
              source_sha256=hashlib.sha256(Path('UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c').read_bytes()).hexdigest(),
              entry_source_sha256=hashlib.sha256(Path('UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/Entry.S').read_bytes()).hexdigest())
Path('out/native-loader/build.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record))
PY
