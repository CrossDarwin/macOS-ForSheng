#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a read-only USB exporter for the observed native XNU log range."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import tarfile
from pathlib import Path
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from range_download import download


def fat_image(include_panic=False):
    """A fixed FAT12 export: two contiguous files, never a physical disk."""
    image = bytearray(2048 * 512)
    image[:3] = b'\xeb\x3c\x90'
    image[3:11] = b'SHENGLOG'
    struct.pack_into('<HBHBHHBHHHII', image, 11, 512, 1, 1, 2, 64, 2048, 0xf8, 6, 1, 1, 0, 0)
    image[36:39] = b'\x80\x00\x29'
    struct.pack_into('<I', image, 39, 0x53484c47)
    image[43:54] = b'SHENGNATLOG'
    image[54:62] = b'FAT12   '
    image[510:512] = b'\x55\xaa'
    table = bytearray(6 * 512)
    def entry(cluster, value):
        at = cluster * 3 // 2
        word = int.from_bytes(table[at:at+2], 'little')
        word = (word & 0x000f) | value << 4 if cluster & 1 else (word & 0xf000) | value
        table[at:at+2] = word.to_bytes(2, 'little')
    entry(0, 0xff8)
    entry(1, 0xfff)
    spans = [(2, 161), (163, 2)] + ([(165, 1024)] if include_panic else [])
    for first, count in spans:
        for cluster in range(first, first+count):
            entry(cluster, 0xfff if cluster == first+count-1 else cluster+1)
    image[512:7*512] = table
    image[7*512:13*512] = table
    files = [(b'NATIVLOGBIN', 2, 82048), (b'STATUS  TXT', 163, 1024)]
    if include_panic:
        files.append((b'XNUPANICBIN', 165, 524288))
    for index, (name, first, size) in enumerate(files):
        at = 13*512 + index*32
        image[at:at+11] = name
        image[at+11] = 0x21
        struct.pack_into('<HI', image, at+26, first, size)
    label = 13 * 512 + len(files) * 32
    image[label:label+11] = b'SHENGNATLOG'
    image[label+11] = 8
    return bytes(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--kernel-build', type=Path, required=True)
    parser.add_argument('--kernel-physical-base', type=lambda value: int(value, 0), required=True,
                        help='actual DarwinBoot load PA from this hardware boot, never the QEMU address')
    parser.add_argument('--boot-template', type=Path, required=True)
    parser.add_argument('--panic-physical-base', type=lambda value: int(value, 0), default=0,
                        help='optional actual panic RAM PA printed by this DarwinBoot run')
    args = parser.parse_args()
    from observe_macos26_kernel import identify
    _, addresses, native = identify(args.kernel_build.resolve())
    if '_sheng_log_buffer' not in addresses:
        raise ValueError('this linked kernel does not contain the native retained logger')
    base = min(segment['va'] for segment in native['segments'] if segment['size'])
    physical = args.kernel_physical_base + addresses['_sheng_log_buffer'] - base
    reserved_bytes = 0x18000
    if physical & 0x3fff or not 0x90000000 <= physical < physical + reserved_bytes <= 0x280000000:
        raise ValueError('native log PA must be aligned in sheng DRAM outside the reader boot window')
    panic = args.panic_physical_base
    if panic:
        if (panic & 0x3fff or not args.kernel_physical_base <= panic < panic + 524288 <= args.kernel_physical_base + 0x20000000
                or not 0x90000000 <= panic < panic + 524288 <= 0x280000000
                or max(physical, panic) < min(physical + reserved_bytes, panic + 524288)):
            raise ValueError('panic PA must be an aligned, disjoint observed range inside the kernel window')
    with args.boot_template.open('rb') as stream:
        template = stream.read(4096)
    if template[:8] != b'ANDROID!' or struct.unpack_from('<I', template, 40)[0] != 4:
        raise ValueError('requires the current-slot Android v4 boot template')
    template_os_version = struct.unpack_from('<I', template, 16)[0]
    if not template_os_version:
        raise ValueError('the boot template OS metadata is missing')
    config = json.loads((ROOT/'config/native-log-reader.json').read_text())
    cache = ROOT/'private/linux-reader'
    cache.mkdir(parents=True, exist_ok=True)
    for asset in config['assets']:
        path = cache/asset['filename']
        if not path.exists():
            if not args.fetch:
                raise ValueError(f'missing {path.name}; use --fetch')
            download(asset['url'], path, asset['bytes'], 4)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != asset['bytes'] or digest != asset['sha256']:
            raise ValueError(f'input hash differs: {path.name}')
    out = ROOT/'out/native-log-reader'/f'{physical:x}-{panic:x}-{native["uuid"]}'
    out.mkdir(parents=True, exist_ok=False)
    subprocess.run(['aarch64-linux-gnu-gcc', '-static', '-Os', '-Wall', '-Wextra', '-Werror',
                    f'-DLOG_BASE=0x{physical:x}ULL', f'-DPANIC_BASE=0x{panic:x}ULL', ROOT/'probes/native_log_reader.c', '-o', out/'init'], check=True)
    source = ROOT/'UniXNU-sheng/package/linux-log/build-linux-log-boot.py'
    spec = importlib.util.spec_from_file_location('upstream_reader', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    archive = out/'package.tar'
    with archive.open('wb') as stream:
        subprocess.run(['dpkg-deb', '--fsys-tarfile', cache/'linux-xiaomi-sheng.deb'], stdout=stream, check=True)
    with tarfile.open(archive) as package:
        matches = [m for m in package.getmembers() if m.name.endswith('/nvmem-reboot-mode.ko.zst')]
        if len(matches) != 1:
            raise ValueError('reader kernel must have exactly one reboot-mode module')
        compressed = package.extractfile(matches[0]).read()
    reset_module = subprocess.check_output(['zstd', '-dq', '-c'], input=compressed)
    boot = (cache/'boot_sheng_singleboot.img').read_bytes()
    kernel_size, kernel_addr, ramdisk_size, _, second_size, _, tags, page, version, os_version = struct.unpack_from('<10I', boot, 8)
    if boot[:8] != b'ANDROID!' or version or ramdisk_size or second_size or page != 4096:
        raise ValueError('unexpected pinned mainline boot container')
    compressed_kernel = boot[page:page+kernel_size]
    decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
    kernel = decoder.decompress(compressed_kernel)
    dtb = decoder.unused_data
    if not decoder.eof or dtb[:4] != b'\xd0\x0d\xfe\xed' or struct.unpack_from('>I', dtb, 4)[0] != len(dtb):
        raise ValueError('expected exactly one gzip Image followed by one DTB')
    (out/'Image').write_bytes(kernel)
    tree = out/'reader.dtb'
    tree.write_bytes(dtb)
    ufs_node = '/soc@0/ufshc@1d84000'
    compatible = subprocess.check_output(['fdtget', '-ts', tree, ufs_node, 'compatible'], text=True)
    if 'qcom,sm8550-ufshc' not in compatible:
        raise ValueError('the pinned reader UFS node differs from sheng')
    subprocess.run(['fdtput', '-ts', tree, ufs_node, 'status', 'disabled'], check=True)
    for field in ('#address-cells', '#size-cells'):
        value = subprocess.check_output(['fdtget', '-tx', tree, '/reserved-memory', field], text=True).strip()
        if value != '2':
            raise ValueError('reader reservation requires two-cell addresses and sizes')
    ranges = [('sheng-native-log', physical, reserved_bytes)]
    if panic:
        ranges.append(('sheng-xnu-panic', panic, 524288))
    for name, address, size in ranges:
        node = f'/reserved-memory/{name}@{address:x}'
        subprocess.run(['fdtput', '-cp', tree, node], check=True)
        subprocess.run(['fdtput', '-t', 'x', tree, node, 'reg', f'{address >> 32:x}',
                        f'{address & 0xffffffff:x}', '0', f'{size:x}'], check=True)
        subprocess.run(['fdtput', tree, node, 'no-map'], check=True)
    patched_kernel = compressed_kernel[:len(compressed_kernel)-len(dtb)] + tree.read_bytes()
    initrd = gzip.compress(module.cpio([
        ('dev', 0o40755, b''), ('proc', 0o40755, b''), ('sys', 0o40755, b''), ('run', 0o40755, b''),
        ('dev/console', 0o20600, b''), ('init', 0o100755, (out/'init').read_bytes()),
        ('ramlog.img', 0o100600, fat_image(bool(panic))), ('nvmem-reboot-mode.ko', 0o100600, reset_module)]), mtime=0)
    header = bytearray(page)
    header[:8] = b'ANDROID!'
    struct.pack_into('<10I', header, 8, len(patched_kernel), kernel_addr, len(initrd), 0x01000000, 0,
                     0x00f00000, tags, page, 0, template_os_version)
    command = b'rdinit=/init console=tty0 loglevel=4 consoleblank=0'
    header[64:64+len(command)] = command
    identity = hashlib.sha1()
    for payload in (patched_kernel, initrd, b''):
        identity.update(payload)
        identity.update(struct.pack('<I', len(payload)))
    header[576:596] = identity.digest()
    pad = lambda data: data + b'\0' * (-len(data) % page)
    image = bytes(header) + pad(patched_kernel) + pad(initrd)
    path = out/'sheng-native-log-reader.img'
    path.write_bytes(image)
    report = dict(kernel_uuid=native["uuid"], kernel_sha256=native["kernel_sha256"],
                  reader="sheng-native-reader-v2", physical_base=physical, log_bytes=82048,
                  panic_physical_base=panic, panic_bytes=524288 if panic else 0,
                  os_version=template_os_version,
                  reserved_bytes=reserved_bytes, observed_kernel_physical_base=args.kernel_physical_base,
                  image=path.name, bytes=len(image), sha256=hashlib.sha256(image).hexdigest(),
                  reader_source_sha256=hashlib.sha256((ROOT/'probes/native_log_reader.c').read_bytes()).hexdigest(),
                  region=dict(base=physical, bytes=reserved_bytes, reader_dtb_nomap=True),
                  ufs_controller_disabled=True, ufs_access=False, hardware_tested=False, retention_qualified=False)
    (out/'build.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
