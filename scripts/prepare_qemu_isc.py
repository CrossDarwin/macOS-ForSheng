#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Format an isolated, empty ISC test disk. Never accepts a host device."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import uuid
import zlib

SIZE = 512 << 20
ROLES = {'SHENG-xART': 0x100, 'SHENG-Preboot': 0x10, 'SHENG-Hardware': 0x140}
ISC_TYPE = uuid.UUID('69646961-6700-11aa-aa11-00306543ecac')


def checksum(block):
    if len(block) != 4096:
        raise ValueError('requires a complete APFS metadata block')
    a = b = 0
    modulus = 0xffffffff
    for word, in struct.iter_unpack('<I', block[8:]):
        a = (a + word) % modulus
        b = (b + a) % modulus
    low = modulus - (a + b) % modulus
    high = modulus - (a + low) % modulus
    return struct.pack('<II', low, high)


def assign_empty_roles(data, identities):
    # Snapintosh/tools/make-isc-fixture.py encodes this same public role field.
    # Only this invocation's fresh, unmounted volumes may be changed.
    if (len(data) != SIZE or data[32:36] != b'NXSB'
            or struct.unpack_from('<IQ', data, 36) != (4096, SIZE // 4096)
            or data[:8] != checksum(data[:4096]) or set(identities) != set(ROLES)):
        raise ValueError('not the fresh formatter output')
    result = bytearray(data)
    changed = []
    seen = set()
    for at in range(0, len(data), 4096):
        block = data[at:at + 4096]
        if block[32:36] != b'APSB':
            continue
        name = block[704:960].split(b'\0', 1)[0].decode('ascii')
        identity = str(uuid.UUID(bytes=bytes(block[240:256]))).lower()
        if (block[:8] != checksum(block) or struct.unpack_from('<I', block, 24)[0] != 13
                or name not in ROLES or identity != identities[name].lower()
                or struct.unpack_from('<H', block, 964)[0] != 0
                or any(struct.unpack_from('<5Q', block, 184))
                or struct.unpack_from('<Q', block, 264)[0] != 1):
            raise ValueError(f'unexpected or nonempty volume superblock at {at:#x}')
        seen.add(name)
        struct.pack_into('<H', result, at + 964, ROLES[name])
        result[at:at + 8] = checksum(result[at:at + 4096])
        changed.append(dict(offset=at, name=name, uuid=identity, role=ROLES[name]))
    if seen != set(ROLES):
        raise ValueError('formatter did not create exactly the three owned volume identities')
    return result, changed


def wrap_gpt(container):
    if len(container) != SIZE:
        raise ValueError('unexpected owned container extent')
    start = 1 << 20
    size = SIZE + (2 << 20)
    sectors = size // 512
    entries = bytearray(16384)
    identity = lambda name: uuid.uuid5(uuid.NAMESPACE_URL, 'sheng://qemu-isc/' + name).bytes_le
    struct.pack_into('<16s16sQQQ72s', entries, 0, ISC_TYPE.bytes_le,
                     identity('partition'), start // 512, (start + SIZE) // 512 - 1,
                     0, 'SHENG test ISC'.encode('utf-16le'))
    crc = zlib.crc32(entries)

    def header(current, other, table):
        block = bytearray(512)
        struct.pack_into('<8sIIIIQQQQ16sQIII', block, 0, b'EFI PART', 0x10000,
                         92, 0, 0, current, other, 34, sectors - 34,
                         identity('disk'), table, 128, 128, crc)
        struct.pack_into('<I', block, 16, zlib.crc32(block[:92]))
        return block

    prefix = bytearray(start)
    struct.pack_into('<B3sB3sII', prefix, 446, 0, b'\x00\x02\x00',
                     0xee, b'\xff\xff\xff', 1, sectors - 1)
    prefix[510:512] = b'\x55\xaa'
    prefix[512:1024] = header(1, sectors - 1, 2)
    prefix[1024:1024 + len(entries)] = entries
    tail = bytearray(size - start - SIZE)
    tail[-512 - len(entries):-512] = entries
    tail[-512:] = header(sectors - 1, 1, sectors - 33)
    return prefix, container, tail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('requires the native macOS APFS formatter')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    transcript = out / 'format.log'

    def run(*command, plist=False):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        with transcript.open('ab') as stream:
            stream.write((' '.join(command) + '\n').encode() + result.stdout + result.stderr + b'\n')
        result.check_returncode()
        return plistlib.loads(result.stdout) if plist else result.stdout.decode()

    seed = out / 'fresh.cdr'
    run('hdiutil', 'create', '-size', '512m', '-layout', 'NONE', '-type', 'UDTO', str(seed))
    attached = run('hdiutil', 'attach', '-nomount', '-nobrowse', '-plist', str(seed), plist=True)
    whole = attached['system-entities'][0]['dev-entry']
    identities = {}
    try:
        images = run('hdiutil', 'info', '-plist', plist=True)['images']
        owned = [i for i in images if Path(i['image-path']).resolve() == seed]
        if len(owned) != 1 or whole not in [e.get('dev-entry') for e in owned[0]['system-entities']]:
            raise ValueError('attachment does not belong to the newly created test file')
        # hdiutil's -fs APFS creates a container limited to one volume.
        # diskutil formats the owned blank image with ordinary container limits.
        run('diskutil', 'apfs', 'createContainer', whole)
        containers = run('diskutil', 'apfs', 'list', '-plist', plist=True)['Containers']
        found = [c for c in containers if whole.removeprefix('/dev/') in
                 [p['DeviceIdentifier'] for p in c.get('PhysicalStores', [])]]
        if len(found) != 1:
            raise ValueError('fresh file has no unique APFS container')
        container = found[0]['ContainerReference']
        # Native formatting supplies all filesystem structures. Roles are assigned
        # offline because xART creation is restricted to entitled host callers.
        for name in ROLES:
            run('diskutil', 'apfs', 'addVolume', container, 'APFS', name, '-nomount')
        containers = run('diskutil', 'apfs', 'list', '-plist', plist=True)['Containers']
        current = [c for c in containers if c['ContainerReference'] == container]
        if len(current) != 1 or len(current[0]['Volumes']) != 3:
            raise ValueError('unexpected test volume count')
        for volume in current[0]['Volumes']:
            if volume.get('MountPoint') or volume['Name'] not in ROLES:
                raise ValueError('test volumes must remain unmounted')
            identities[volume['Name']] = volume['APFSVolumeUUID']
    finally:
        run('hdiutil', 'detach', whole)
    source = seed.read_bytes()
    source_hash = hashlib.sha256(source).hexdigest()
    data, changed = assign_empty_roles(source, identities)
    disk = out / 'isc.raw'
    digest = hashlib.sha256()
    with disk.open('xb') as stream:
        for chunk in wrap_gpt(data):
            stream.write(chunk)
            digest.update(chunk)
    record = dict(schema='sheng-qemu-isc-v1', bytes=disk.stat().st_size,
                  sha256=digest.hexdigest(), partition_type=str(ISC_TYPE),
                  container_offset=1 << 20, container_bytes=SIZE,
                  container_sha256=hashlib.sha256(data).hexdigest(),
                  formatter_source_sha256=source_hash, superblocks=changed,
                  roles=ROLES, volumes=identities, sep_trusted_storage=False,
                  guest_read_only=True, host_devices_modified=False,
                  root_disk_modified=False, hardware_admitted=False,
                  host_version=run('sw_vers').strip())
    (out / 'isc.json').write_text(json.dumps(record, indent=2) + '\n')
    seed.unlink()
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
