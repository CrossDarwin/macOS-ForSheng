#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage a pinned QR encoder without libc, heap allocation or assertion callbacks."""
import hashlib
import json
from pathlib import Path


def render(root: Path) -> tuple[str, dict]:
    config = json.loads((root / 'config/macos26-panic-qr.json').read_text())
    if (config['repository'] != 'nayuki/QR-Code-generator'
            or config['revision'] != '3c6d0b3cefb4e049dc337e82237c9644399716a8'
            or config['payload_bytes_max'] != 640 or config['reason_bytes_max'] != 256
            or config['version_max'] != 20 or config['network_url'] is not False):
        raise ValueError('unexpected panic QR contract')
    directory = root / 'platform/sheng/macos26/log/qr'
    for name, expected in config['files'].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError('pinned QR source differs: ' + name)
    source = (directory / 'qrcodegen.c').read_text()
    includes = '#include <assert.h>\n#include <limits.h>\n#include <stdlib.h>\n#include <string.h>\n'
    if source.count(includes) != 1:
        raise ValueError('unexpected QR library includes')
    prefix = '''/* Freestanding adaptation; the unmodified source and MIT notice are retained. */
#include "pe_sheng_qr_runtime.h"
#pragma push_macro("assert")
#undef assert
#define assert(condition) ((void)sizeof(condition))
#define memset sheng_qr_memset
#define memcpy sheng_qr_memcpy
#define memmove sheng_qr_memmove
#define strlen sheng_qr_strlen
#define strchr sheng_qr_strchr
#define abs(x) ((x) < 0 ? -(x) : (x))
#define labs(x) ((x) < 0 ? -(x) : (x))
'''
    suffix = '''
#undef labs
#undef abs
#undef strchr
#undef strlen
#undef memmove
#undef memcpy
#undef memset
#pragma pop_macro("assert")
'''
    return source.replace(includes, prefix).replace('LONG_MAX', '__LONG_MAX__') + suffix, config
