#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compile pinned, memory-only Recovery UI page policies for development XNU."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

PAGE = 16384
SCHEMA = 'sheng-recovery-ui-pages-v1'


def validate(document: dict) -> list[dict]:
    if (document.get('schema') != SCHEMA or document.get('build') != '25F71'
            or document.get('architecture') != 'arm64e' or document.get('default_off') is not True
            or document.get('disk_writes') is not False or document.get('authentication_success_fabricated') is not False):
        raise ValueError('Requires the explicit 25F71 ARM64E development UI contract')
    pages = document.get('pages', [])
    if not 1 <= len(pages) <= 32:
        raise ValueError('Invalid Recovery UI page count')
    seen = set()
    for page in pages:
        name, offset = page['file'], page['file_offset']
        if (not re.fullmatch(r'[A-Za-z0-9_. -]{1,96}', name) or name in ('.', '..')
                or type(offset) is not int or not 0 <= offset <= (1 << 40) - PAGE or offset % PAGE
                or (name, offset) in seen):
            raise ValueError('Invalid or duplicate Recovery UI file extent')
        seen.add((name, offset))
        for key in ('before_sha256', 'after_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', page[key]):
                raise ValueError('Invalid Recovery UI page digest')
        if page['before_sha256'] == page['after_sha256']:
            raise ValueError('UI policy must change the selected page')
        edits = page['edits']
        if not 1 <= len(edits) <= 4:
            raise ValueError('Invalid per-page UI edit count')
        occupied = set()
        for edit in edits:
            at = edit['offset']
            if not all(isinstance(edit.get(key), str) and re.fullmatch(r'(?:[0-9a-f]{8}){1,4}', edit[key])
                       for key in ('before', 'after')):
                raise ValueError('Invalid ARM64 instruction encoding')
            before, after = bytes.fromhex(edit['before']), bytes.fromhex(edit['after'])
            if (type(at) is not int or not 0 <= at < PAGE or at % 4 or not 0 < len(before) <= 16
                    or len(before) % 4 or len(before) != len(after) or at + len(before) > PAGE or before == after):
                raise ValueError('Invalid bounded ARM64 instruction edit')
            extent = set(range(at, at + len(before)))
            if occupied & extent:
                raise ValueError('Overlapping UI edits')
            occupied.update(extent)
    return pages


def verify_page(page: bytes, rule: dict) -> bytes:
    if len(page) != PAGE or hashlib.sha256(page).hexdigest() != rule['before_sha256']:
        raise ValueError('Original authenticated page differs from the UI policy')
    result = bytearray(page)
    for edit in rule['edits']:
        at, before, after = edit['offset'], bytes.fromhex(edit['before']), bytes.fromhex(edit['after'])
        if result[at:at + len(before)] != before:
            raise ValueError('Original UI instruction differs')
        result[at:at + len(after)] = after
    if hashlib.sha256(result).hexdigest() != rule['after_sha256']:
        raise ValueError('Resulting UI page differs from its pinned digest')
    return bytes(result)


def render(document: dict) -> str:
    pages = validate(document)
    def array(value: str) -> str:
        return '{' + ', '.join(f'0x{x:02x}' for x in bytes.fromhex(value)) + '}'
    lines = ['// SPDX-License-Identifier: MIT', '// Generated from the pinned Recovery UI page manifest.',
             '#pragma once', 'static const struct sheng_ui_page sheng_ui_pages[] = {']
    for page in pages:
        lines.extend(['    {', f'        .file = "{page["file"]}",',
                      f'        .file_offset = {page["file_offset"]}ULL,',
                      f'        .before_sha256 = {array(page["before_sha256"])},',
                      f'        .after_sha256 = {array(page["after_sha256"])},',
                      f'        .edit_count = {len(page["edits"])},', '        .edits = {'])
        for edit in page['edits']:
            lines.append('            {' + f'.offset = {edit["offset"]}, .size = {len(bytes.fromhex(edit["before"]))}, '
                         + f'.before = {array(edit["before"])}, .after = {array(edit["after"])}' + '},')
        lines.extend(['        },', '    },'])
    lines.extend(['};', ''])
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.manifest.read_text())
    result = render(document)
    if not args.output.exists() or args.output.read_text() != result:
        args.output.write_text(result)


if __name__ == '__main__':
    main()
