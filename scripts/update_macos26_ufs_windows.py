#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Append a verified ISC seed inside existing macosroot; commit its manifest last."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import uuid

from create_log_partition import geometry
from install_macos26_ufs_root import PARTITION
from repartition_macos26_root import BLOCK, WINDOW, ROOT, Device


def validate_update(previous, candidate, plan, contract):
    if (previous.get('partition') != 'macosroot' or candidate.get('partition') != 'macosroot'
            or previous.get('root_lun') != 0 or candidate.get('root_lun') != 0
            or candidate.get('android_userdata_used') is not False
            or candidate.get('isc_volatile_overlay') is not True
            or previous.get('build') != '25F71' or candidate.get('build') != '25F71'
            or len(previous.get('windows', [])) != 1 or len(candidate.get('windows', [])) != 2):
        raise ValueError('requires the existing OS and exactly one new volatile ISC seed')
    before = previous['windows'][0]
    os_window, isc = candidate['windows']
    keys = ('name', 'offset', 'bytes', 'sha256')
    if (any(before.get(k) != os_window.get(k) for k in keys)
            or os_window['name'] != 'OS' or os_window['offset'] != WINDOW
            or os_window['bytes'] != contract['bytes'] or os_window['sha256'] != contract['sha256']):
        raise ValueError('the existing BaseSystem extent must remain unchanged')
    if (isc.get('name') != 'ISC' or isc.get('bytes') != contract['isc']['bytes']
            or isc.get('sha256') != contract['isc']['sha256']
            or type(isc.get('offset')) is not int or isc['offset'] % WINDOW
            or isc['bytes'] % WINDOW or isc['offset'] < previous['image_bytes']
            or candidate['image_bytes'] != isc['offset'] + isc['bytes']
            or candidate['image_bytes'] > plan['root_bytes']):
        raise ValueError('ISC extent must be paired, disjoint and inside macosroot')
    return os_window, isc


def image_digest(image, windows):
    digest = hashlib.sha256()
    payloads = [hashlib.sha256() for _ in windows]
    with image.open('rb') as stream:
        offset = 0
        while data := stream.read(8 * WINDOW):
            digest.update(data)
            for window, payload in zip(windows, payloads):
                start = max(offset, window['offset'])
                end = min(offset + len(data), window['offset'] + window['bytes'])
                if start < end:
                    payload.update(data[start - offset:end - offset])
            offset += len(data)
    if any(payload.hexdigest() != window['sha256'] for window, payload in zip(windows, payloads)):
        raise ValueError('candidate payload differs from its compiled window identity')
    return digest.hexdigest()


def update(device, plan_dir, previous_root, previous_deployment, candidate_dir, output):
    plan = json.loads((plan_dir / 'plan.json').read_text())
    previous = json.loads((previous_root / 'build.json').read_text())
    installed = json.loads(previous_deployment.read_text())
    candidate = json.loads((candidate_dir / 'build.json').read_text())
    contract = json.loads((ROOT / 'config/macos26-recovery-root.json').read_text())
    os_window, isc = validate_update(previous, candidate, plan, contract)
    if (plan.get('applied') is not True or plan.get('gpt_readback_verified') is not True
            or plan.get('serial') != device.serial or plan.get('disk_lbas') != device.lbas
            or installed.get('status') != 'verified' or installed.get('readback_verified') is not True
            or installed.get('destination') != PARTITION
            or installed.get('destination_guid') != plan['root_unique_guid']
            or installed.get('sha256') != plan.get('root_image_sha256')
            or installed.get('sha256') != installed.get('readback_sha256')):
        raise ValueError('requires the recorded, verified current root deployment')
    image = candidate_dir / 'macosroot.img'
    manifest = (candidate_dir / 'manifest.bin').read_bytes()
    expected = bytearray(BLOCK)
    expected[:8] = b'SHNGROOT'
    struct.pack_into('<IIQ', expected, 8, 1, 2, candidate['image_bytes'])
    for i, window in enumerate((os_window, isc)):
        struct.pack_into('<32sQQII32s40s', expected, 24 + i * 128,
            window['name'].encode(), window['offset'], window['bytes'], 512, 1,
            bytes.fromhex(window['sha256']), bytes(40))
    expected[4064:] = hashlib.sha256(expected[:4064]).digest()
    if (manifest != expected or hashlib.sha256(manifest).hexdigest() != candidate['manifest_sha256']
            or image.stat().st_size != candidate['image_bytes']):
        raise ValueError('candidate manifest differs from the admitted windows')
    with image.open('rb') as source:
        if source.read(BLOCK) != manifest:
            raise ValueError('candidate image has a different manifest')
    digest = image_digest(image, (os_window, isc))
    device.require_recovery()
    for kind, start in (('primary', 0), ('secondary', device.lbas - WINDOW // BLOCK)):
        raw = device.read(start, WINDOW // BLOCK)
        if raw != (plan_dir / f'after-{kind}.bin').read_bytes():
            raise ValueError('LUN0 changed since the applied partition plan')
        _, _, entries, _, _, stride = geometry(raw, device.lbas, start)
        entry = entries[(plan['root_index'] - 1) * stride:plan['root_index'] * stride]
        if (entry[16:32] != uuid.UUID(plan['root_unique_guid']).bytes_le
                or struct.unpack_from('<QQ', entry, 32) != (plan['root_first_lba'], plan['root_last_lba'])):
            raise ValueError('macosroot identity or extent changed')
    if (device.shell('readlink -f ' + PARTITION) != '/dev/block/sda' + str(plan['root_index'])
            or int(device.shell('blockdev --getsize64 ' + PARTITION)) != plan['root_bytes']
            or device.shell(f'ls -A /sys/class/block/sda{plan["root_index"]}/holders')):
        raise ValueError('kernel macosroot node is not the admitted unmounted extent')
    old_manifest = (previous_root / 'manifest.bin').read_bytes()
    # Partition and parent block nodes have distinct caches in Recovery.
    def flush_aliases():
        device.shell(f'blockdev --flushbufs {PARTITION} && blockdev --flushbufs /dev/block/sda', timeout=120)
    flush_aliases()
    if device.read(plan['root_first_lba'], 1) != old_manifest:
        raise ValueError('current manifest differs; no automatic rewrite')
    def remote_digest(offset, size):
        if offset % 512 or size % 512:
            raise ValueError('unaligned bounded readback')
        return device.shell(f'set -o pipefail; dd if={PARTITION} bs={WINDOW} skip={offset} '
                            f'count={size} iflag=skip_bytes,count_bytes | sha256sum', timeout=180).split()[0]
    if remote_digest(os_window['offset'], os_window['bytes']) != os_window['sha256']:
        raise ValueError('BaseSystem changed before the update; no writes performed')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / 'manifest-before.bin').write_bytes(old_manifest)
    record = dict(serial=device.serial, started_at=datetime.now(timezone.utc).isoformat(),
        destination=PARTITION, destination_guid=plan['root_unique_guid'], bytes=candidate['image_bytes'],
        sha256=digest, status='prepared', image_write_attempts=0, gpt_writes=False,
        android_userdata_modified=False, base_system_written=False, manifest_committed=False,
        isc_offset=isc['offset'], isc_bytes=isc['bytes'], previous_sha256=installed['sha256'])
    def save():
        (output / 'deployment.json').write_text(json.dumps(record, indent=2) + '\n')
    save()
    try:
        record.update(status='writing-isc-seed', image_write_attempts=1)
        save()
        with image.open('rb') as source, (output / 'write-isc.log').open('w') as log:
            source.seek(isc['offset'])
            # Toybox count_bytes bounds pipe input by bytes, including short reads.
            command = f'dd of={PARTITION} bs={WINDOW} seek={isc["offset"] // WINDOW} count={isc["bytes"]} iflag=count_bytes conv=notrunc,fsync'
            subprocess.run(device.adb + ['shell', '-T', command], stdin=source, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=300)
        if remote_digest(isc['offset'], isc['bytes']) != isc['sha256']:
            raise ValueError('ISC readback differs; original manifest retained, no automatic retry')
        record['manifest_committed'] = None
        record['status'] = 'committing-manifest'
        save()
        with (output / 'write-manifest.log').open('w') as log:
            subprocess.run(device.adb + ['shell', '-T', f'dd of={PARTITION} bs={BLOCK} count={BLOCK} iflag=count_bytes conv=notrunc,fsync'],
                           input=manifest, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
        record['manifest_committed'] = True
        save()
        flush_aliases()
        if device.read(plan['root_first_lba'], 1) != manifest:
            raise ValueError('manifest readback differs; no automatic retry')
        record['status'] = 'verifying-complete-root'
        save()
        observed = remote_digest(0, candidate['image_bytes'])
        record['readback_sha256'] = observed
        if observed != digest:
            raise ValueError('complete root readback differs; no automatic retry')
        record.update(status='verified', readback_verified=True,
                      completed_at=datetime.now(timezone.utc).isoformat())
        save()
        plan.update(root_image_bytes=candidate['image_bytes'], root_image_sha256=digest,
                    root_image_readback_verified=True)
        (plan_dir / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
        return record
    except BaseException as error:
        record.update(failed_phase=record['status'], status='failed', error=str(error))
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--partition-plan', required=True, type=Path)
    parser.add_argument('--previous-root', required=True, type=Path)
    parser.add_argument('--previous-deployment', required=True, type=Path)
    parser.add_argument('--candidate-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(update(Device(args.serial), args.partition_plan, args.previous_root,
        args.previous_deployment, args.candidate_root, args.output), indent=2))


if __name__ == '__main__':
    main()
