# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the SGI instructions emitted by the Mach-O assembler."""
from pathlib import Path
import struct

from native_macho import macho, symbols


def audit_sgi(path: Path, functions: tuple[str, ...]) -> dict:
    data = path.read_bytes()
    image = macho(data)
    names = symbols(path)
    text = next(section for segment in image['segments'] for section in segment['sections']
                if section['name'] == '__text')
    start, end = text['va'], text['va'] + text['size']
    result = {}
    for name in functions:
        address = names[name]
        if not start <= address < end:
            raise ValueError(f'SGI entry outside executable text: {name}')
        limit = min((value for value in names.values() if address < value < end), default=end)
        offset = text['fileoff'] + address - start
        code = data[offset:offset + limit - address]
        if len(code) % 4:
            raise ValueError(f'Unaligned SGI function extent: {name}')
        words = [word[0] for word in struct.iter_unpack('<I', code)]
        sends = [i for i, word in enumerate(words) if word & 0xffffffe0 == 0xd518cba0]
        if not sends or not any(0xd5033fdf in words[i + 1:] for i in sends):
            raise ValueError(f'Missing emitted ICC_SGI1R_EL1 write or following ISB: {name}')
        result[name] = dict(sgi1r_writes=len(sends), following_isb=True)
    return result
