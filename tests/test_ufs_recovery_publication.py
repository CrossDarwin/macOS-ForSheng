# SPDX-License-Identifier: MIT
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecoveryPublication(unittest.TestCase):
    def test_real_coordinator_single_root_and_legacy_policy(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        coordinator = ROOT / 'UniXNU/drivers/NativeUfs/RootPublication.h'
        if not compiler or not coordinator.exists():
            self.skipTest('requires the pinned UFS source and host C++ compiler')
        contract = json.loads((ROOT / 'config/macos26-recovery-root.json').read_text())
        header = ROOT / 'platform/sheng/macos26/storage/recovery_root.h'
        digest = ','.join(str(b) for b in bytes.fromhex(contract['sha256']))
        isc = contract['isc']
        isc_digest = ','.join(str(b) for b in bytes.fromhex(isc['sha256']))
        recovery = f'''#include <cstdint>
#include <cstring>
#include <cassert>
#include <vector>
#define NATIVE_UFS_RECOVERY_BYTES {contract['bytes']}ULL
#define NATIVE_UFS_RECOVERY_DIGEST {{{digest}}}
#define NATIVE_UFS_RECOVERY_UUID "{contract['volume_uuid'].upper()}"
#define NATIVE_UFS_ISC_BYTES {isc['bytes']}ULL
#define NATIVE_UFS_ISC_DIGEST {{{isc_digest}}}
#define NATIVE_UFS_ISC_UUID "{isc['volume_uuid'].upper()}"
#include "{header}"
#include "{coordinator}"
struct Ops {{
  bool live=false, valid=true, scheduled=false, scheduleOk=true, startOk=true, waitOk=true;
  unsigned discards=0;
  bool prepare(unsigned i) {{ assert(i==0); live=true; return true; }}
  bool validate() {{ return valid; }}
  bool schedule() {{ scheduled=true; return scheduleOk; }}
  bool start(unsigned i) {{ assert(i==0 && live); return startOk; }}
  bool wait(unsigned i) {{ assert(i==0 && live); return waitOk; }}
  void discard(unsigned i) {{ assert(i==0 && live); live=false; ++discards; }}
}};
int main() {{
  const char *names[]={{"OS"}}, *wrong[]={{"SystemOS"}}, *missing[]={{nullptr}};
  UfsRootPlan plan;
  assert(ufsBuildRootPlan(names,1,plan) && plan.count==1 && plan.order[0]==0);
  UfsRootPlan bad;
  assert(!ufsBuildRootPlan(wrong,1,bad) && !bad.count);
  assert(!ufsBuildRootPlan(missing,1,bad));
  assert(!ufsBuildRootPlan(names,0,bad));
  uint8_t digest[32]=NATIVE_UFS_RECOVERY_DIGEST;
  assert(ufsRecoveryRootIdentity("OS",NATIVE_UFS_RECOVERY_BYTES,digest));
  digest[17]^=1;
  assert(!ufsRecoveryRootIdentity("OS",NATIVE_UFS_RECOVERY_BYTES,digest));
  digest[17]^=1;
  assert(!ufsRecoveryRootIdentity("SystemOS",NATIVE_UFS_RECOVERY_BYTES,digest));
  assert(!ufsRecoveryRootIdentity("OS",NATIVE_UFS_RECOVERY_BYTES-512,digest));
  char id[37]; assert(ufsRecoveryRootUuid("OS",NATIVE_UFS_RECOVERY_BYTES,id));
  assert(!strcmp(id,NATIVE_UFS_RECOVERY_UUID));
  assert(!ufsRecoveryRootUuid("OS",512,id));
  const char *paired[]={{"OS","ISC"}}, *reversed[]={{"ISC","OS"}}, *duplicate[]={{"OS","OS"}};
  UfsRootPlan both;
  assert(ufsBuildRootPlan(paired,2,both) && both.order[0]==1 && both.order[1]==0);
  assert(ufsBuildRootPlan(reversed,2,both) && both.order[0]==0 && both.order[1]==1);
  assert(!ufsBuildRootPlan(duplicate,2,bad));
  uint8_t iscDigest[32]=NATIVE_UFS_ISC_DIGEST;
  assert(ufsRecoveryRootIdentity("ISC",NATIVE_UFS_ISC_BYTES,iscDigest));
  assert(!ufsRecoveryRootIdentity("OS",NATIVE_UFS_ISC_BYTES,iscDigest));
  iscDigest[0]^=1; assert(!ufsRecoveryRootIdentity("ISC",NATIVE_UFS_ISC_BYTES,iscDigest));
  assert(ufsRecoveryRootUuid("ISC",NATIVE_UFS_ISC_BYTES,id) && !strcmp(id,NATIVE_UFS_ISC_UUID));

  {{ Ops o; o.valid=false; auto r=ufsPrepareRootWindows(o,1);
     assert(r.phase==UfsRootPhase::Identity && !o.live && !o.scheduled && o.discards==1); }}
  {{ Ops o; o.scheduleOk=false; auto r=ufsPrepareRootWindows(o,1);
     assert(r.phase==UfsRootPhase::Schedule && !o.live && o.discards==1); }}
  for(unsigned failure=0;failure<3;++failure) {{
    Ops o; assert(ufsPrepareRootWindows(o,1).phase==UfsRootPhase::Complete);
    o.startOk=failure!=1; o.waitOk=failure!=2;
    auto r=ufsPublishRootWindows(o,plan);
    assert(r.phase==(failure==1?UfsRootPhase::Start:failure==2?UfsRootPhase::Media:UfsRootPhase::Complete));
    assert(r.published==(failure==1?0:1));
    assert(o.live==(failure!=1));
  }}
}}
'''
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for name, source in (('recovery', recovery),
                                 ('legacy', (coordinator.parent / 'tests/RootPublication.cpp').read_text().replace(
                                     '#include "../RootPublication.h"', f'#include "{coordinator}"'))):
                cpp, executable = folder / (name + '.cpp'), folder / name
                cpp.write_text(source)
                subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                '-fsanitize=address,undefined', str(cpp), '-o', str(executable)],
                               check=True, capture_output=True, timeout=30)
                subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
