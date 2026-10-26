# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded concurrent HTTP ranges with a durable resume map and final caller verification."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time
import urllib.request


def download(url, path: Path, size: int, jobs: int):
    chunk = 32 << 20
    state_path = path.with_suffix(path.suffix + '.ranges.json')
    identity = dict(url=url, size=size, chunk=chunk)
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['identity'] != identity or not path.is_file() or path.stat().st_size != size:
            raise ValueError('range resume map does not match input')
        done = set(state['done'])
    else:
        prefix = path.stat().st_size if path.exists() else 0
        if prefix > size:
            raise ValueError('partial input exceeds expected length')
        done = set(range(prefix // chunk))
    total = (size + chunk - 1) // chunk
    if any(type(i) is not int or not 0 <= i < total for i in done):
        raise ValueError('invalid completed range index')
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    lock = threading.Lock()
    def save():
        temporary = state_path.with_suffix(state_path.suffix + '.tmp')
        temporary.write_text(json.dumps(dict(identity=identity, done=sorted(done))))
        temporary.replace(state_path)
    try:
        os.ftruncate(fd, size)
        save()
        def fetch(index):
            start = index * chunk
            end = min(start + chunk, size) - 1
            for attempt in range(4):
                try:
                    request = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}'})
                    with urllib.request.urlopen(request, timeout=60) as response:
                        if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                            raise ValueError('server did not honor the exact byte range')
                        data = response.read(end - start + 2)
                    if len(data) != end - start + 1:
                        raise ValueError('short or oversized range response')
                    written = 0
                    while written < len(data):
                        n = os.pwrite(fd, memoryview(data)[written:], start + written)
                        if n <= 0:
                            raise OSError('range write made no progress')
                        written += n
                    with lock:
                        os.fsync(fd)
                        done.add(index)
                        save()
                        if len(done) % 16 == 0 or len(done) == total:
                            print(f'Ranges {len(done)}/{total}', flush=True)
                    return
                except (OSError, ValueError):
                    if attempt == 3:
                        raise
                    time.sleep(attempt + 1)
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            for _ in executor.map(fetch, [i for i in range(total) if i not in done]):
                pass
    finally:
        os.close(fd)
