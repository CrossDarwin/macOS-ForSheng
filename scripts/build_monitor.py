#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile Snapintosh's existing monitor without connecting to hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Snapintosh/probes'))
import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm-bin', type=Path, required=True)
    args = parser.parse_args()
    for tool in ('clang', 'llvm-objcopy'):
        if not (args.llvm_bin / tool).is_file():
            raise ValueError(f'missing {tool}')
    run.LLVM = args.llvm_bin.resolve()
    linker = args.llvm_bin / 'ld.lld'
    run.LLD = str(linker) if linker.is_file() else shutil.which('ld.lld')
    if not run.LLD:
        raise ValueError('ld.lld is required')
    directory = ROOT / 'out/monitor'
    payload = run.build('xnuboot', directory)
    record = dict(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload),
                  source='Snapintosh/probes/xnuboot.*', hardware_executed=False,
                  sheng_qualified=False, note='Upstream A16 monitor build; not a sheng launch image')
    record['compiler'] = subprocess.check_output([str(args.llvm_bin/'clang'), '--version'], text=True).splitlines()[0]
    record['flags'] = run.FLAGS
    record['sources_lock_sha256'] = hashlib.sha256((ROOT/'sources.lock.json').read_bytes()).hexdigest()
    (directory / 'build.json').write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
