#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Capture selected sheng facts; no reboot, root transition or partition writes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
QUERIES = {
    'identity': 'getprop ro.product.device; uname -r; getprop ro.boot.slot_suffix',
    'boot_properties_unverified': 'getprop ro.boot.flash.locked; getprop ro.boot.vbmeta.device_state',
    'memory': 'head -3 /proc/meminfo',
    'data': 'df -k /data; mount | grep " /data "',
    'virtualization': 'ls -l /dev/kvm /dev/gunyah; ls /sys/module | grep -E "kvm|hyp|gunyah"',
    'root': 'id; command -v su',
    'gpt_geometry': 'cat /sys/class/block/sda29/start /sys/class/block/sda29/size /sys/block/sda/queue/logical_block_size',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', help='required when more than one device is connected')
    parser.add_argument('--cpu-probe', type=Path, help='push and run the compiled read-only EL0 probe')
    parser.add_argument('--output', type=Path, default=ROOT / 'private/device/android.json')
    args = parser.parse_args()
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])
    def shell(command):
        p = subprocess.run([*adb, 'shell', command], capture_output=True, text=True, timeout=30)
        return {'exit_code': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
    if shell('getprop ro.product.device')['stdout'] != 'sheng':
        raise ValueError('select exactly one sheng device')
    report = {'captured_at': datetime.now(timezone.utc).isoformat(), 'scope': 'android-userspace',
              'runtime_qualified': False, 'facts': {name: shell(cmd) for name, cmd in QUERIES.items()}}
    if args.cpu_probe:
        remote = '/data/local/tmp/macos-for-sheng-cpu-id'
        subprocess.run([*adb, 'push', str(args.cpu_probe), remote], check=True)
        try:
            result = shell(f'chmod 700 {remote} && {remote}')
            if result['exit_code']:
                raise RuntimeError(result)
            report['cpu_probe'] = json.loads(result['stdout'])
        finally:
            shell(f'rm -f {remote}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Captured {args.output}; EL2/NV2 hardware qualification remains pending')


if __name__ == '__main__':
    main()
