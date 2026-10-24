#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write only the prepared macosroot partition from root sheng Recovery."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import uuid

from create_log_partition import geometry
from repartition_macos26_root import BLOCK, WINDOW, Device


PARTITION = '/dev/block/by-name/macosroot'


def install(device, plan_dir, root_dir, output):
    plan = json.loads((plan_dir / 'plan.json').read_text())
    build = json.loads((root_dir / 'build.json').read_text())
    image = root_dir / 'macosroot.img'
    manifest = (root_dir / 'manifest.bin').read_bytes()
    if (plan.get('applied') is not True or plan.get('gpt_readback_verified') is not True
            or plan.get('serial') != device.serial or plan.get('root_name') != 'macosroot'
            or build.get('partition') != 'macosroot' or build.get('build') != '25F71'
            or build.get('root_lun') != 0 or build.get('android_userdata_used') is not False
            or build['image_bytes'] != image.stat().st_size or image.stat().st_size % WINDOW
            or image.stat().st_size > plan['root_bytes'] or len(manifest) != BLOCK
            or manifest[:8] != b'SHNGROOT'
            or hashlib.sha256(manifest[:4064]).digest() != manifest[4064:]
            or hashlib.sha256(manifest).hexdigest() != build['manifest_sha256']):
        raise ValueError('requires the applied dedicated partition and paired root image')
    device.require_recovery()
    for kind, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        current = device.read(start, WINDOW // BLOCK)
        expected = (plan_dir / f'after-{kind}.bin').read_bytes()
        # 主备GPT所在窗口仍逐字节匹配，不能静默接受其他分区修改
        if current != expected:
            raise ValueError('LUN0 layout changed since the applied partition plan')
        _, _, entries, _, _, stride = geometry(current, device.lbas, start)
        entry = entries[(plan['root_index'] - 1) * stride:plan['root_index'] * stride]
        if (entry[16:32] != uuid.UUID(plan['root_unique_guid']).bytes_le
                or struct.unpack_from('<QQ', entry, 32) != (plan['root_first_lba'], plan['root_last_lba'])):
            raise ValueError('macosroot identity or extent differs from the plan')
    if (device.shell('readlink -f ' + PARTITION) != '/dev/block/sda' + str(plan['root_index'])
            or int(device.shell('blockdev --getsize64 ' + PARTITION)) != plan['root_bytes']
            or device.shell(f'ls -A /sys/class/block/sda{plan["root_index"]}/holders')):
        raise ValueError('kernel macosroot node differs from the verified GPT')
    log = device.shell('cat /tmp/recovery.log')
    if ('Data wipe complete.' not in log
            or f'wipe metadata encrypted /dev/block/bootdevice/by-name/userdata with size {plan["userdata_bytes"]}' not in log):
        raise ValueError('requires completed Recovery wipe of the resized encrypted userdata')
    with image.open('rb') as stream:
        if stream.read(BLOCK) != manifest:
            raise ValueError('root image manifest differs from the prepared manifest')
        stream.seek(0)
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / 'recovery-wipe.log').write_text(log)
    record = dict(serial=device.serial, started_at=datetime.now(timezone.utc).isoformat(),
                  destination=PARTITION, destination_guid=plan['root_unique_guid'],
                  bytes=image.stat().st_size, sha256=digest, status='prepared',
                  userdata_discard_authorized=True, gpt_writes=False, image_write_attempts=0)
    def save():
        (output / 'deployment.json').write_text(json.dumps(record, indent=2) + '\n')
    save()
    record['status'] = 'discarding-dedicated-root'
    save()
    device.shell('blkdiscard ' + PARTITION)
    record.update(status='writing-root', image_write_attempts=1)
    save()
    with image.open('rb') as source, (output / 'write.log').open('w') as log_stream:
        subprocess.run(device.adb + ['shell', '-T', 'dd of=' + PARTITION + ' bs=1048576 conv=notrunc,fsync'], stdin=source, stdout=log_stream,
            stderr=subprocess.STDOUT, check=True, timeout=240)
    record['status'] = 'verifying-root'
    save()
    device.shell('sync; blockdev --flushbufs ' + PARTITION, timeout=120)
    count = image.stat().st_size // WINDOW
    observed = device.shell(f'set -o pipefail; dd if={PARTITION} bs=1048576 count={count} 2>/tmp/sheng-root-readback.log | sha256sum', timeout=120).split()[0]
    (output / 'readback.log').write_text(device.shell('cat /tmp/sheng-root-readback.log') + '\n')
    record['readback_sha256'] = observed
    if observed != digest:
        record['status'] = 'readback-mismatch'
        save()
        raise ValueError('macosroot readback differs; no automatic retry')
    record.update(status='verified', readback_verified=True, completed_at=datetime.now(timezone.utc).isoformat())
    save()
    plan.update(root_image_written=True, root_image_bytes=image.stat().st_size,
                root_image_sha256=digest, root_image_readback_verified=True,
                userdata_contents_discarded=True,
                userdata_recovery_wipe_completed=True, userdata_filesystem_rebuilt=False,
                userdata_format_pending_vold=True)
    (plan_dir / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--partition-plan', required=True, type=Path)
    parser.add_argument('--root-build', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(install(Device(args.serial), args.partition_plan, args.root_build, args.output), indent=2))


if __name__ == '__main__':
    main()
