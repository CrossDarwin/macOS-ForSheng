#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage hash-pinned reconstructed inputs and build the upstream sheng archives."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stage(tree: Path) -> dict:
    pin = json.loads((ROOT / 'config/sheng-reconstructed-inputs.json').read_text())
    cache = ROOT / 'private/build-inputs'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / pin['asset']
    if not archive.exists():
        subprocess.run(['gh', 'release', 'download', pin['release'], '--repo', pin['repository'],
                        '--pattern', pin['asset'], '--dir', str(cache)], check=True)
    if archive.stat().st_size != pin['bytes'] or sha(archive) != pin['sha256']:
        raise ValueError('reconstructed input archive does not match its fixed hash')
    unpacked = cache / (pin['release'] + '-extracted')
    unpacked.mkdir(exist_ok=True)
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or any(
            not member.isfile() or Path(member.name).is_absolute() or '..' in Path(member.name).parts
            for member in members
        ):
            raise ValueError('require unique regular relative files in the private input archive')
        if sum(member.size for member in members) > 400 * 1024**2:
            raise ValueError('unexpected reconstructed input expansion')
        bundle.extractall(unpacked, members=members, filter='data')
    inventory_path = unpacked / 'inventory.json'
    if sha(inventory_path) != pin['inventory_sha256']:
        raise ValueError('input inventory identity changed')
    inventory = json.loads(inventory_path.read_text())
    if set(names) != {*inventory['files'], 'inventory.json'}:
        raise ValueError('unexpected files in the input archive')
    for name, record in inventory['files'].items():
        path = unpacked / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'input inventory mismatch: {name}')
    plan = json.loads((unpacked / 'candidate.json').read_text())
    provenance = json.loads((unpacked / 'source-build.json').read_text())
    if (plan['candidate_sha256'] != pin['candidate_sha256'] or
            plan['original_sha256'] != pin['original_kernelcache_sha256'] or
            provenance['kernel_sha256'] != sha(unpacked / 'source-kernel.macho') or
            plan['native_sha256'] != provenance['kernel_sha256'] or
            not provenance['original_abi_bootstrap_only'] or
            provenance['config']['XNU_CRYPTO_BOOTSTRAP'] != 'prelinked'):
        raise ValueError('original-component bootstrap provenance mismatch')
    for component in ('storage', 'legacy'):
        snapshot = json.loads((unpacked / component / 'gdb-stop.json').read_text())
        if snapshot['kernel_sha256'] != plan['candidate_sha256'] or snapshot['bounded_timeout_interrupted']:
            raise ValueError(f'{component}: require the actual completed matching QEMU observation')

    def put(source: Path, relative: str) -> None:
        destination = tree / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and sha(destination) == sha(source):
            return
        if destination.exists() or destination.is_symlink():
            raise ValueError(f'refuse to replace a different existing dependency: {destination}')
        shutil.copy2(source, destination)

    for name in ('native-owner-ufs-rootauth3-candidate', 'native-owner-mobile-graphics-candidate'):
        for extension, source in [('macho', 'candidate.macho'), ('json', 'candidate.json')]:
            put(unpacked / source, f'build/native-prelink/{name}.{extension}')
    put(unpacked / 'kernelcache.macho', '.cache/firmware/kernelcache.macho/kernelcache.release.ipad7.decompressed')
    put(unpacked / 'storage/gdb-stop.json', 'build/darwinboot-storage-native-metadata/gdb-stop.json')
    put(unpacked / 'legacy/gdb-stop.json', 'build/darwinboot-owner-hvf-mobile-graphics-legacy-class/gdb-stop.json')
    for component in ('os', 'systemos'):
        for source in (unpacked / 'policies' / component).iterdir():
            put(source, f'build/verified-root-{component}/{source.name}')
    (tree / 'build/display-analysis').mkdir(parents=True, exist_ok=True)
    result = dict(archive_sha256=pin['sha256'], inventory_sha256=pin['inventory_sha256'],
                  candidate_sha256=plan['candidate_sha256'],
                  source_kernel_sha256=provenance['kernel_sha256'],
                  source_ci_run=inventory['source_ci_run'], runtime_observation='QEMU TCG',
                  hardware_tested=False, macos_userspace_qualified=False, archives_built=False)
    (tree / 'build/reconstructed-inputs.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def build(tree: Path, env: dict | None = None) -> None:
    commands = [
        ['extract-files.py', '--device', str(ROOT / 'UniXNU-sheng')],
        ['fetch-adreno-inputs.py'],
        ['fetch-sheng-dts.py'],
        ['prepare-sheng-gmu.py'],
        ['prepare-sheng-gmu-votes.py'],
        ['audit-storage-interface.py', '--candidate', 'build/native-prelink/native-owner-ufs-rootauth3-candidate.macho'],
        ['audit-amfi-pmgr-contract.py'],
        ['audit-mobile-graphics-legacy.py'],
        ['build-verified-root-probe.py', '--component', 'os', '--include-systemos'],
        ['build-arm-driver.py', 'NativeVirtioBlock', '--verified-root', '--verified-root-bundle'],
        ['build-native-virtio-bindings.py', '--directory', 'build/native-virtio-block-verified-bundle'],
    ]
    for index, command in enumerate(commands, 1):
        log = tree / 'build' / f'reconstructed-{index:02d}-{command[0]}.log'
        print('Reconstruct:', ' '.join(command), flush=True)
        with log.open('w') as stream:
            completed = subprocess.run([sys.executable, str(tree / 'scripts' / command[0]), *command[1:]],
                                       cwd=tree, env=env, stdout=stream, stderr=subprocess.STDOUT)
        if completed.returncode:
            print(log.read_text()[-6000:], file=sys.stderr)
            raise subprocess.CalledProcessError(completed.returncode, command)
    path = tree / 'build/reconstructed-inputs.json'
    record = json.loads(path.read_text())
    record['archives_built'] = True
    record['archives'] = {name: sha(tree / name) for name in (
        'build/verified-root-os-xnu-bundle/libVerifiedRootProbe.a',
        'build/native-virtio-block-verified-bundle/libNativeVirtioBlock.a')}
    path.write_text(json.dumps(record, indent=2) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--compile', action='store_true')
    args = parser.parse_args()
    tree = args.tree.resolve()
    stage(tree)
    if args.compile:
        build(tree, dict(os.environ))
    print('PASS: pinned reconstructed inputs' + (' and source-built archives' if args.compile else ' staged'))


if __name__ == '__main__':
    main()
