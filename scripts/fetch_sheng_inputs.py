#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch the exact upstream iPadOS inputs for the sheng hardware baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import struct
import sys
import tomllib
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
from unixnu import ipsw


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-only', action='store_true', help='omit the two original verification-policy volumes')
    args = parser.parse_args()
    board_path = ROOT / 'UniXNU-sheng/board.toml'
    baseline = json.loads((ROOT / 'config/sheng-baseline.json').read_text())
    if sha(board_path) != baseline['board_sha256']:
        raise ValueError('upstream board differs from its pinned baseline')
    board = tomllib.loads(board_path.read_text())
    ctx = SimpleNamespace(board=board, out_root=ROOT / 'private/apple/sheng-reference',
                          option_text=lambda *_: None)
    source = ipsw.Ipsw(ctx)
    components = list(board['ipsw']['fetch'])
    if not args.boot_only:
        components += ['OS', 'Cryptex1,SystemOS']
    needed = sum(source.info(component)[1] for component in components)
    if shutil.disk_usage(ROOT).free < needed + 8 * 1024**3:
        raise ValueError('insufficient disk space for the exact baseline inputs and reserve')
    results = {}
    for component in components:
        path = source.extract(component)
        expected = board['ipsw'].get('sha256', {}).get(path.name)
        digest = sha(path)
        if expected and digest != expected:
            raise ValueError(f'{component}: upstream input hash mismatch')
        results[component] = {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
                              'sha256': digest, 'upstream_hash_verified': bool(expected)}
        print(f'PASS {component}: {path.name} {digest}', flush=True)
    if platform.system() == 'Darwin':
        decoded = ipsw.kernelcache(ctx, source)
    else:
        import lzfse
        payload = ipsw.im4p_payload((ROOT / results['KernelCache']['path']).read_bytes())
        data = lzfse.decompress(payload)
        if data[:4] == b'\xca\xfe\xba\xbe':
            count = struct.unpack_from('>I', data, 4)[0]
            if count > 16:
                raise ValueError('unexpected kernelcache slice count')
            slices = [struct.unpack_from('>5I', data, 8 + index * 20) for index in range(count)]
            candidates = [item for item in slices if item[0] == 0x100000c]
            if len(candidates) != 1:
                raise ValueError('requires one original ARM64 kernelcache slice')
            _, _, offset, size, _ = candidates[0]
            if offset + size > len(data):
                raise ValueError('kernelcache slice exceeds input')
            data = data[offset:offset + size]
        expected = board['kernel']['prelink']['kernelcache_sha256']
        if data[:4] != b'\xcf\xfa\xed\xfe' or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('original ARM64 kernelcache does not match the upstream pin')
        decoded = source.cache / 'kernelcache.decompressed'
        decoded.write_bytes(data)
    results['decompressed_kernelcache'] = {'path': str(decoded.relative_to(ROOT)), 'sha256': sha(decoded)}
    record = {'purpose': 'Unchanged iPadOS 17 hardware baseline; never paired with macOS userspace',
              'build': board['ipsw']['build'], 'board_sha256': sha(board_path), 'inputs': results,
              'full_configuration_built': False, 'private_abi_evidence_reconstructed': False}
    (source.cache / 'sheng-inputs.json').write_text(json.dumps(record, indent=2) + '\n')
    print('PASS upstream sheng Apple inputs; ABI and policy archives still require reconstruction')


if __name__ == '__main__':
    main()
