#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate bounded Language Chooser diagnostics for the pinned 25F71 image."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

from native_macho import macho
from native_recovery_ui import PAGE, render as render_pages, verify_page

ROOT = Path(__file__).resolve().parents[1]
SITES = (
    (0x8b64, 'system-language-count', 'cbnz_x0', 0),
    (0x90cc, 'localized-name-present', 'mov_x0', 24),
    (0xcbd8, 'table-row-count', 'mov_x0', 20),
    (0xccc0, 'row-view-present', 'mov_x0', 19),
    (0xcc5c, 'row-value-present', 'mov_x0', 20),
)


def validate(document: dict) -> None:
    if (document.get('trace_schema') != 'sheng-language-trace-v1'
            or document.get('boot_argument') != 'sheng-language-trace=1'
            or document.get('original_signature_validation_required') is not True):
        raise ValueError('Requires the explicit default-off Language Chooser trace contract')
    render_pages(document)
    if (not isinstance(document.get('uuid_command_offset'), int)
            or not 32 <= document['uuid_command_offset'] <= 4096 - 24
            or len(bytes.fromhex(document['uuid_command'])) != 24
            or bytes.fromhex(document['uuid_command'])[:8] != struct.pack('<II', 0x1b, 24)
            or len(document.get('points', [])) != len(SITES)):
        raise ValueError('Invalid pinned Language Chooser identity')
    edits = {}
    for page in document['pages']:
        if page['file'] != 'Language Chooser':
            raise ValueError('Trace pages must belong to Language Chooser')
        for edit in page['edits']:
            edits[page['file_offset'] + edit['offset']] = edit
    if len(edits) != len(SITES):
        raise ValueError('Trace pages differ from the observed sites')
    for index, (point, site) in enumerate(zip(document['points'], SITES)):
        rva, name, replay, destination = site
        if (point.get('rva'), point.get('name'), point.get('replay'), point.get('destination')) != site:
            raise ValueError('Unknown Language Chooser trace site')
        if point.get('tag') != 0x5a01 + index or point.get('file_offset') != rva:
            raise ValueError('Invalid trace tag or file position')
        before = int(point['instruction'], 16)
        expected = 0xb50000a0 if replay == 'cbnz_x0' else 0xaa0003e0 | destination
        edit = edits[rva]
        if (before != expected or edit['before'] != struct.pack('<I', before).hex()
                or edit['after'] != struct.pack('<I', 0xd4200000 | point['tag'] << 5).hex()):
            raise ValueError('Trace instruction cannot be replayed exactly')


def verify_binary(document: dict, data: bytes) -> None:
    validate(document)
    image = macho(data, 'arm64e')
    text, = [s for s in image['segments'] if s['name'] == '__TEXT']
    if text['va'] != 0x100000000 or text['fileoff'] != 0:
        raise ValueError('Unexpected Language Chooser address layout')
    offset = document['uuid_command_offset']
    if (hashlib.sha256(data).hexdigest() != document['binary_sha256']
            or data[offset:offset + 24].hex() != document['uuid_command']):
        raise ValueError('Language Chooser does not match the pinned 25F71 image')
    for page in document['pages']:
        start = page['file_offset']
        verify_page(data[start:start + PAGE], page)


def render(document: dict) -> str:
    validate(document)
    output = '#ifdef SHENG_LANGUAGE_TRACE_PAGE_TABLE\n'
    output += render_pages(document).replace('sheng_ui_pages[]', 'sheng_language_trace_pages[]')
    output += '#else\nstatic const struct sheng_language_point sheng_language_points[] = {\n'
    for point in document['points']:
        output += ('    {' + f'.rva = 0x{point["rva"]:x}, .tag = 0x{point["tag"]:x}, '
                   + f'.destination = {point["destination"]}, '
                   + f'.branch = {int(point["replay"] == "cbnz_x0")}, .name = "{point["name"]}"' + '},\n')
    output += '};\n'
    output += f'#define SHENG_LANGUAGE_UUID_OFFSET {document["uuid_command_offset"]}u\n'
    output += 'static const uint8_t sheng_language_uuid_command[24] = {'
    output += ', '.join(f'0x{x:02x}' for x in bytes.fromhex(document['uuid_command'])) + '};\n'
    return output + '#endif\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'config/macos26-language-trace.json')
    parser.add_argument('--binary', type=Path, help='Verify the original local image without modifying it')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not args.binary and not args.output:
        parser.error('Provide --binary or --output')
    document = json.loads(args.manifest.read_text())
    result = render(document)
    if args.binary:
        verify_binary(document, args.binary.read_bytes())
        print('Language Chooser identity, page digests and all five replay sites match')
    if args.output:
        args.output.write_text(result)


if __name__ == '__main__':
    main()
