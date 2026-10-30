# SPDX-License-Identifier: GPL-3.0-or-later
"""Qualify a local language-selector fixture before enabling physical GOP scanout."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def language_pixels(path):
    """Count visible regions in the fixed 800x600 QEMU acceptance display."""
    data = path.read_bytes()
    if (not 33 <= len(data) <= 3 << 20 or data[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
            or struct.unpack_from('>II', data, 16) != (800, 600)):
        raise ValueError('requires the original 800x600 QMP PNG')
    raw = subprocess.check_output(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
        '-i', str(path.resolve()), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], timeout=15)
    if len(raw) != 800 * 600 * 3:
        raise ValueError('incomplete QMP image decode')

    def count(rect, predicate):
        x0, y0, x1, y1 = rect
        return sum(predicate(*raw[(y * 800 + x) * 3:(y * 800 + x) * 3 + 3])
                   for y in range(y0, y1) for x in range(x0, x1))
    return dict(selected_row_blue_pixels=count((268, 327, 514, 351), lambda r, g, b: b > 140 and b > g * 1.3 and r < 80),
                title_light_pixels=count((340, 180, 465, 207), lambda r, g, b: min(r, g, b) > 130),
                language_rows_light_pixels=count((268, 230, 532, 508), lambda r, g, b: min(r, g, b) > 130))


def qualify_language_selector(build, fixture, identity):
    fixture = fixture.resolve()
    inputs = {}

    def read(name):
        if Path(name).name != name:
            raise ValueError('evidence must remain in the named fixture')
        path = fixture / name
        inputs[name] = digest(path)
        return json.loads(path.read_text())

    compiled = json.loads((build / 'build.json').read_text())['recovery_ui_policy']
    policy = json.loads((ROOT / 'config/macos26-recovery-ui-pages.json').read_text())
    for key, name in (('manifest_sha256', 'config/macos26-recovery-ui-pages.json'),
                      ('engine_sha256', 'platform/sheng/macos26/recovery/ui_policy.h'),
                      ('kernel_hook_sha256', 'platform/sheng/macos26/recovery/ui_policy_kernel.h')):
        if compiled.get(key) != digest(ROOT / name):
            raise ValueError('requires the current compiled UI policy')
    if (compiled.get('default_off') is not True or compiled.get('disk_writes') is not False
            or compiled.get('original_signature_validation_required') is not True):
        raise ValueError('requires authenticated, memory-only UI policies')
    driver = json.loads((build / 'security-relink.json').read_text())['storage_driver']
    display = driver['build']['native_gop_display']
    from native_framebuffer import display_cpus
    reference = json.loads((ROOT / 'config/macos26-gop-reference.json').read_text())
    if (display.get('default_off') is not True or display.get('gpu_acceleration') is not False
            or display.get('publishes_vm_identity') is not False or 1 not in display_cpus(display)
            or display.get('reference') != 'https://github.com/' + reference['repository'] + '/tree/' + reference['revision']
            or display.get('input_sha256') != {k: v['canonical_sha256'] for k, v in reference['files'].items()}):
        raise ValueError('requires the pinned GOP source')
    for key, name in (('patch_sha256', '0001-native-gop-display.patch'),
                      ('scanout_sha256', 'gop_scanout.h'), ('layer_selection_sha256', 'gop_layers.h')):
        if display.get(key) != digest(ROOT / 'platform/sheng/macos26/display' / name):
            raise ValueError('requires the current compiled GOP inputs')
    source = read('qualification-inputs.json')
    snapshot = read('gdb-stop.json')
    if (any(source['kernel'].get(k) != identity[k] for k in ('uuid', 'kernel_sha256'))
            or snapshot.get('kernel_sha256') != identity['kernel_sha256']
            or source.get('compiled_policy') != compiled):
        raise ValueError('UI evidence differs from the packaged kernel')
    audit = read('debugger-write-audit.json')
    if (audit.get('debugger_user_memory_writes') != 0 or audit.get('debugger_user_pc_writes') != 0
            or audit.get('original_base_system_readonly') is not True
            or audit.get('policy_controller_loaded') is not False):
        raise ValueError('requires the audited native UI execution')
    geometry = read('qmp-springboard-transition.json')
    ui = geometry['native_ui_policy']
    frame = geometry['native_gop_geometry']
    if (geometry.get('guest_memory_modified') is not False or geometry.get('guest_registers_modified') is not False
            or ui.get('_sheng_recovery_ui_enabled') != 1
            or ui.get('_sheng_recovery_ui_pages_applied') != len(policy['pages'])
            or ui.get('_sheng_recovery_ui_page_mask') != (1 << len(policy['pages'])) - 1
            or frame.get('completed_frames', 0) < 1
            or [frame.get('display_width'), frame.get('display_height')] != [800, 600]):
        raise ValueError('requires actual native UI pages and completed GOP frames')
    selected = read('after-chinese-click-2-state.json')
    continued = read('continue-followup-state.json')
    for state in (selected, continued):
        if (state.get('read_only') is not True or state.get('process', {}).get('name') != 'Language Chooser'
                or state.get('selected_language_constant_text') != 'zh-Hans'):
            raise ValueError('requires original Chinese selection state')
    if selected.get('state_machine') != 6 or continued.get('state_machine') not in (4, 8, 9):
        raise ValueError('requires a real Continue state transition')
    for name in ('simplified-chinese-click-2.json', 'continue-after-chinese.json'):
        event = read(name)
        if (event.get('events_submitted') is not True or event.get('guest_memory_modified') is not False
                or event.get('guest_registers_modified') is not False or event.get('device', {}).get('absolute') is not True):
            raise ValueError('requires real QMP input events')
    series = read('language-window-visibility-series.json')
    samples = series.get('samples', [])
    if series.get('read_only') is not True or len(samples) != 6 or len({s['file'] for s in samples}) != 6:
        raise ValueError('requires six original visibility samples')
    measurements = []
    for sample in samples:
        name = sample['file']
        if Path(name).name != name:
            raise ValueError('image must remain in the named fixture')
        actual = language_pixels(fixture / name)
        if (actual['selected_row_blue_pixels'] < 1000 or actual['title_light_pixels'] < 500
                or actual['language_rows_light_pixels'] < 1000):
            raise ValueError('language title, list or selected row is absent')
        inputs[name] = digest(fixture / name)
        measurements.append(actual)
    return dict(schema='sheng-language-selector-qemu-v1', kernel_uuid=identity['uuid'],
        kernel_sha256=identity['kernel_sha256'], fixture=str(fixture), evidence_sha256=inputs,
        measurements=measurements, language_selector_visible=True, selected_language='zh-Hans',
        real_continue_processed=True, recovery_tools_window_qualified=False,
        software_scanout=True, gpu_acceleration=False, physical_display_qualified=False,
        physical_input_qualified=False, debugger_user_memory_writes=0, debugger_user_pc_writes=0)
