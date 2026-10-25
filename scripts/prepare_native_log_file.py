#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare an owned contiguous snapshot file inside a backed-up macoslog FAT image."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from native_log_file import BLOCK, CONTRACT, FILE_BYTES, guard, locate, preserve_allocations, contiguous_empty_file


def prepare(source: Path, output: Path) -> dict:
    if source.stat().st_size != 64 << 20:
        raise ValueError('requires the exact existing 64 MiB macoslog image')
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    image = output/'macoslog.img'
    try:
        shutil.copy2(source, image)
        # mcopy must create a new file; an existing file requires explicit inspection.
        listing = subprocess.check_output(['mdir', '-b', '-i', str(image), '::/'], text=True)
        if any(line.rsplit('/', 1)[-1].upper() == CONTRACT['filename'] for line in listing.splitlines()):
            raise ValueError('log file already exists; preserve and inspect its captures')
        empty = output/'empty-slot.bin'
        with empty.open('wb') as stream:
            stream.truncate(FILE_BYTES)
        subprocess.run(['mcopy', '-i', str(image), str(empty), '::/'+CONTRACT['filename']],
                       check=True, capture_output=True, timeout=30)
        empty.unlink()
        original = source.read_bytes()
        raw = contiguous_empty_file(original, image.read_bytes())
        image.write_bytes(raw)
        offset = locate(raw)
        first = CONTRACT['partition_first'] + offset//BLOCK
        marker = guard(first)
        with image.open('r+b') as stream:
            stream.seek(offset+FILE_BYTES-BLOCK)
            stream.write(marker)
        observed = image.read_bytes()
        preserve_allocations(original, observed)
        if locate(observed) != offset or observed[offset+FILE_BYTES-BLOCK:offset+FILE_BYTES] != marker:
            raise ValueError('prepared file extent or guard differs')
        record = dict(schema=CONTRACT['schema'], allocated_image_sha256=hashlib.sha256(raw).hexdigest(),
            original_image_sha256=hashlib.sha256(original).hexdigest(), existing_allocations_preserved=True,
            image_sha256=hashlib.sha256(observed).hexdigest(), file_first_lba=first,
            file_relative_offset=offset, file_bytes=FILE_BYTES, guard_sha256=hashlib.sha256(marker).hexdigest(),
            partition_uuid=CONTRACT['partition_uuid'], gpt_writes=False, deployed=False)
        (output/'build.json').write_text(json.dumps(record, indent=2)+'\n')
        return record
    except BaseException:
        # Remove only this new failed candidate, keeping the source backup intact.
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.image, args.output), indent=2))


if __name__ == '__main__':
    main()
