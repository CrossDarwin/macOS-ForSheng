# SPDX-License-Identifier: MIT
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UfsMediaWait(unittest.TestCase):
    def test_delayed_initialization_and_missing_identity(self):
        compiler = shutil.which('clang++') or shutil.which('g++')
        header = ROOT / 'UniXNU/drivers/NativeUfs/RootMediaWait.h'
        if not compiler or not header.exists():
            self.skipTest('requires compiler and patched UFS source')
        source = '''#include <cassert>
#include <vector>
#include "HEADER"
struct Wait {
    unsigned elapsed=0, readyAt=0, queries=0;
    bool uuidAndAncestorMatch=true;
    std::vector<unsigned> reports;
    bool ready() { ++queries; return uuidAndAncestorMatch && elapsed>=readyAt; }
    void pause(unsigned ms) { assert(ms==100); elapsed+=ms; }
    void progress(unsigned ms) { assert(ms==elapsed); reports.push_back(ms); }
};
int main() {
    { Wait w; assert(ufsWaitForRootMedia(w) && w.elapsed==0 && w.queries==1); }
    // Initialization may finish after the former 30-second window.
    { Wait w; w.readyAt=45000; assert(ufsWaitForRootMedia(w) && w.elapsed==45000);
      assert((w.reports==std::vector<unsigned>{0,10000,20000,30000,40000})); }
    { Wait w; w.readyAt=180000; assert(ufsWaitForRootMedia(w) && w.elapsed==180000); }
    // Neither timeout nor a wrong UUID may be treated as a successful mount.
    for(bool match: {false,true}) {
      Wait w; w.uuidAndAncestorMatch=match; w.readyAt=match?180100:100;
      assert(!ufsWaitForRootMedia(w) && w.elapsed==180000 && w.queries==1801);
      assert(w.reports.size()==19 && w.reports.back()==180000);
    }
}
'''.replace('HEADER', str(header))
        with tempfile.TemporaryDirectory() as folder:
            cpp, executable = Path(folder) / 'wait.cpp', Path(folder) / 'wait'
            cpp.write_text(source)
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', str(cpp), '-o', str(executable)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
