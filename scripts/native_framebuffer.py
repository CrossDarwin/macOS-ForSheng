# SPDX-License-Identifier: GPL-3.0-or-later
"""Bind SMP display admission to the compiled shared framebuffer owner."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def owner_hash() -> str:
    return hashlib.sha256((ROOT / 'platform/sheng/macos26/log/framebuffer_owner.h').read_bytes()).hexdigest()


def display_cpus(display: dict) -> list[int]:
    if display.get('required_cpus') == 1 and 'supported_cpus' not in display:
        return [1]
    if (display.get('supported_cpus') == [1, 2, 4, 8]
            and display.get('framebuffer_owner_sha256') == owner_hash()):
        return [1, 2, 4, 8]
    raise ValueError('Requires the compiled framebuffer owner contract')


def require_smp_owner(build: dict) -> None:
    owner = build.get('framebuffer_owner', {})
    patch = ROOT / 'platform/sheng/macos26/patches/0065-native-panic-framebuffer-owner.patch'
    if (owner.get('version') != 1 or owner.get('source_sha256') != owner_hash()
            or owner.get('max_cpus') != 8 or owner.get('late_panic_redraw') is not True
            or owner.get('panic_bypasses_writer') is not True
            or build.get('patches', {}).get(str(patch.relative_to(ROOT)))
            != hashlib.sha256(patch.read_bytes()).hexdigest()):
        raise ValueError('SMP graphics requires the compiled framebuffer owner and panic redraw')
