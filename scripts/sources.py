#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch pinned source trees without resetting existing checkouts."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(directory, *args, capture=False):
    return subprocess.run(['git', '-C', str(directory), *args], check=True,
                          text=True, stdout=subprocess.PIPE if capture else None).stdout


def fetch(entry):
    directory = ROOT / entry['path']
    if not directory.exists():
        directory.mkdir(parents=True)
        git(directory, 'init', '-q')
        git(directory, 'remote', 'add', 'origin', entry['url'])
    if not (directory / '.git').exists():
        raise ValueError(f'{entry["path"]}: existing directory is not a Git checkout')
    remote = git(directory, 'remote', 'get-url', 'origin', capture=True).strip()
    if remote.removesuffix('.git') != entry['url'].removesuffix('.git'):
        raise ValueError(f'{entry["path"]}: unexpected origin')
    current = subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
                             text=True, capture_output=True)
    if current.returncode or current.stdout.strip() != entry['commit']:
        if git(directory, 'status', '--porcelain', capture=True).strip():
            raise ValueError(f'{entry["path"]}: refusing to change a dirty checkout')
        if entry.get('sparse'):
            git(directory, 'sparse-checkout', 'set', '--cone', *entry['sparse'])
        git(directory, 'fetch', '--depth=1', 'origin', entry['commit'])
        git(directory, 'checkout', '--detach', 'FETCH_HEAD')
    if entry.get('submodules'):
        git(directory, 'submodule', 'update', '--init', '--depth=1', '--jobs=4')
    for parent, paths in entry.get('nested_submodules', {}).items():
        git(directory / parent, 'submodule', 'update', '--init', '--depth=1', '--jobs=4', '--', *paths)
    print(f'PIN {entry["path"]} {entry["commit"]}')


def verify(entry):
    directory = ROOT / entry['path']
    if git(directory, 'rev-parse', 'HEAD', capture=True).strip() != entry['commit']:
        raise ValueError(f'{entry["path"]}: commit differs from lock')
    if entry.get('submodules'):
        status = git(directory, 'submodule', 'status', capture=True)
        if any(line[:1] != ' ' for line in status.splitlines()):
            raise ValueError(f'{entry["path"]}: missing or mismatched submodule')
    for parent, paths in entry.get('nested_submodules', {}).items():
        status = git(directory / parent, 'submodule', 'status', '--', *paths, capture=True)
        if any(line[:1] != ' ' for line in status.splitlines()):
            raise ValueError(f'{entry["path"]}/{parent}: missing required nested submodule')
    print(f'PASS {entry["path"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('fetch', 'verify'))
    parser.add_argument('--group', choices=('core', 'feeds', 'graphics', 'macos26', 'all'), default='core')
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    args = parser.parse_args()
    entries = json.loads(args.lock.read_text())['sources']
    for entry in entries:
        if args.group == 'all' or entry['group'] == args.group:
            (fetch if args.action == 'fetch' else verify)(entry)


if __name__ == '__main__':
    main()
