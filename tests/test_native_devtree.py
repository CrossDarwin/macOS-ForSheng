# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from native_devtree import configure_native_text_state, seed_vm_nvram_uuid
from prepare_macos26_qemu_ui import inspect_identity, prepare


def node(name, properties=(), children=()):
    props = (('name', name.encode() + b'\0'), *properties)
    return (struct.pack('<II', len(props), len(children)) +
            b''.join(struct.pack('<32sI', key.encode(), len(value)) + value + bytes(-len(value) % 4)
                     for key, value in props) + b''.join(children))


def read_tree(data):
    result = {}
    def read(at, parents):
        count, children = struct.unpack_from('<II', data, at)
        at += 8
        props = {}
        for _ in range(count):
            key, size = struct.unpack_from('<32sI', data, at)
            at += 36
            props[key.rstrip(b'\0').decode()] = data[at:at + size]
            at += (size + 3) & ~3
        path = (*parents, props['name'].rstrip(b'\0').decode())
        result[path] = props
        for _ in range(children):
            at = read(at, path)
        return at
    assert read(0, ()) == len(data)
    return result


def empty_bank():
    bank = bytearray(8192)
    for offset, name, size in ((0, b'nvram', 32), (32, b'common', 2064), (2096, b'free', 6096)):
        header = bytearray(struct.pack('<BBH12s', 0x70, 0, size // 16, name))
        checksum = sum(header)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        header[1] = checksum
        bank[offset:offset + 16] = header
    struct.pack_into('<I', bank, 16, zlib.adler32(bank[20:]))
    return bytes(bank)


class NativeTree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'kernel.adt'
        self.path.write_bytes(node('device-tree', children=(node('chosen', (('nvram-proxy-data', empty_bank()),)), node('options'))))
        self.root = uuid.UUID('808eac5e-8275-478d-814c-2229d8eb8d07')
        self.vm = uuid.UUID('7e8b064b-8ddb-54c4-b332-6fe0c34f937c')

    def test_input_ecam_is_explicit_and_cannot_enter_hardware_tree(self):
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'development fixture'):
            configure_native_text_state(self.path, qemu_virtio_input=True)
        with self.assertRaisesRegex(ValueError, 'owned QEMU'):
            configure_native_text_state(self.path, development_root=True, qemu_virtio_input=True)
        self.assertEqual(self.path.read_bytes(), original)
        self.path.write_bytes(node('device-tree', (('model', b'qemu-entry-fixture\0'),),
                                  (node('chosen'),)))
        configure_native_text_state(self.path, development_root=True, qemu_virtio_input=True)
        before = self.path.read_bytes()
        tree = read_tree(before)
        props = tree[('device-tree', 'native-recovery-input')]
        self.assertEqual(props['reg'], struct.pack('<QQ', 0x4010000000, 0x100000))
        self.assertEqual(props['compatible'], b'sheng,qemu-virtio-input\0')
        configure_native_text_state(self.path, development_root=True, qemu_virtio_input=True)
        self.assertEqual(self.path.read_bytes(), before)

    def test_recovery_volume_and_vm_identity_use_distinct_abis(self):
        options = dict(development_root=True, root_hash=bytes(range(32)),
                       boot_volume_uuid=self.root, platform_uuid=self.vm)
        configure_native_text_state(self.path, **options)
        before = self.path.read_bytes()
        tree = read_tree(before)
        chosen = tree[('device-tree', 'chosen')]
        self.assertEqual(chosen['boot-uuid'], str(self.root).upper().encode() + b'\0')
        self.assertEqual(chosen['apfs-preboot-uuid'], chosen['boot-uuid'])
        self.assertEqual(tree[('device-tree', 'options')]['platform-uuid'], self.vm.bytes)
        bank = chosen['nvram-proxy-data']
        self.assertEqual(struct.unpack_from('<I', bank, 16)[0], zlib.adler32(bank[20:]))
        self.assertEqual(bank[48:79], b'platform-uuid=' + self.vm.bytes + b'\0')
        self.assertEqual(tree[('device-tree', 'chosen', 'secure-boot-hashes')]['system-volume-auth-blob'], bytes(range(32)))
        configure_native_text_state(self.path, **options)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'conflicts|replace existing'):
            configure_native_text_state(self.path, **(options | dict(platform_uuid=self.root)))
        self.assertEqual(self.path.read_bytes(), before)

    def test_vm_identity_cannot_leak_into_hardware_tree(self):
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'development fixture'):
            configure_native_text_state(self.path, platform_uuid=self.vm)
        with self.assertRaisesRegex(ValueError, 'nil'):
            configure_native_text_state(self.path, development_root=True, platform_uuid=uuid.UUID(int=0))
        with self.assertRaisesRegex(ValueError, 'root hash'):
            configure_native_text_state(self.path, boot_volume_uuid=self.root)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unavailable_vm_sleep_uses_native_defaults_without_hardware_changes(self):
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'development fixture'):
            configure_native_text_state(self.path, qemu_disable_sleep=True)
        self.assertEqual(self.path.read_bytes(), before)
        configure_native_text_state(self.path, development_root=True, qemu_disable_sleep=True)
        configured = self.path.read_bytes()
        self.assertEqual(read_tree(configured)[('device-tree', 'defaults')]['sleep-disabled'], struct.pack('<I', 1))
        configure_native_text_state(self.path, development_root=True, qemu_disable_sleep=True)
        self.assertEqual(self.path.read_bytes(), configured)
        self.path.write_bytes(node('device-tree', children=(node('chosen'), node('defaults', (('sleep-disabled', bytes(4)),)))))
        conflicting = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            configure_native_text_state(self.path, development_root=True, qemu_disable_sleep=True)
        self.assertEqual(self.path.read_bytes(), conflicting)

    def test_nvram_binary_escaping_and_existing_variable_refusal(self):
        identity = uuid.UUID(bytes=bytes([0, 255]) * 8)
        result = seed_vm_nvram_uuid(empty_bank(), identity)
        self.assertEqual(result[62:94], bytes([255, 1, 255, 129]) * 8)
        with self.assertRaisesRegex(ValueError, 'replace existing'):
            seed_vm_nvram_uuid(result, self.vm)
        damaged = bytearray(empty_bank())
        damaged[48] = 1
        with self.assertRaisesRegex(ValueError, 'CHRP'):
            seed_vm_nvram_uuid(bytes(damaged), self.vm)

    def test_missing_options_is_refused_without_rewriting_tree(self):
        before = node('device-tree', children=(node('chosen'),))
        self.path.write_bytes(before)
        with self.assertRaisesRegex(ValueError, 'complete generated'):
            configure_native_text_state(self.path, development_root=True, platform_uuid=self.vm)
        self.assertEqual(self.path.read_bytes(), before)

    def test_gop_descriptor_is_explicit_native_and_idempotent(self):
        self.path.write_bytes(node('device-tree', children=(node('chosen'), node('arm-io'))))
        configure_native_text_state(self.path)
        self.assertNotIn(('device-tree', 'arm-io', 'native-gop'), read_tree(self.path.read_bytes()))
        configure_native_text_state(self.path, native_gop_display=True)
        before = self.path.read_bytes()
        display = read_tree(before)[('device-tree', 'arm-io', 'native-gop')]
        self.assertEqual(display['device_type'], b'display-subsystem\0')
        self.assertEqual(display['compatible'], b'sheng,gop-framebuffer\0')
        self.assertNotIn(b'paravirtualizedgraphics', before)
        configure_native_text_state(self.path, native_gop_display=True)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_or_conflicting_gop_descriptor_is_refused(self):
        for children in ((node('chosen'),), (node('chosen'), node('arm-io', children=(
                node('native-gop', (('compatible', b'other-display\0'),)),)))):
            self.path.write_bytes(node('device-tree', children=children))
            before = self.path.read_bytes()
            with self.assertRaises(ValueError):
                configure_native_text_state(self.path, native_gop_display=True)
            self.assertEqual(self.path.read_bytes(), before)

    def test_ui_esp_requires_matching_dt_and_nvram_identity(self):
        self.assertIsNone(inspect_identity(self.path))
        configure_native_text_state(self.path, development_root=True, platform_uuid=self.vm)
        self.assertEqual(inspect_identity(self.path), self.vm)
        self.path.write_bytes(node('device-tree', children=(
            node('chosen', (('nvram-proxy-data', empty_bank()),)),
            node('options', (('platform-uuid', self.vm.bytes),)))))
        with self.assertRaisesRegex(ValueError, 'differ|incomplete'):
            inspect_identity(self.path)

    def test_prepare_ui_copy_preserves_source_and_refuses_identity_replacement(self):
        source = Path(self.temp.name) / 'source'
        relative = Path('EFI/UniXNU/Payloads/kernel.macho.adt')
        (source / relative).parent.mkdir(parents=True)
        original = self.path.read_bytes()
        (source / relative).write_bytes(original)
        output = Path(self.temp.name) / 'ui'
        prepare(source, output, self.vm)
        self.assertEqual((source / relative).read_bytes(), original)
        self.assertEqual(inspect_identity(output / relative), self.vm)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            prepare(source, output, self.vm)
        with self.assertRaisesRegex(ValueError, 'existing VM identity'):
            prepare(output, Path(self.temp.name) / 'other-ui', self.root)
        self.assertFalse((Path(self.temp.name) / 'other-ui').exists())
        alias = Path(self.temp.name) / 'source-alias'
        alias.symlink_to(source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'inside the source'):
            prepare(source, alias / 'nested', self.vm)

    def test_actual_sheng_recovery_tree_preserves_hardware_identity(self):
        generator = Path(__file__).resolve().parents[1] / 'UniXNU-sheng/scripts/make-sheng-adt.py'
        if not generator.exists():
            self.skipTest('requires the pinned hardware tree generator')
        subprocess.run([sys.executable, str(generator), '--output', str(self.path),
                        '--dram-size', '0x200000000', '--owned-memory-size', '0xc0000000',
                        '--os-environment', 'recoveryos', '--panic-log',
                        '--root-match-volume-uuid', str(self.root)],
                       check=True, capture_output=True, timeout=10)
        configure_native_text_state(self.path, development_root=True,
                                    root_hash=bytes(range(32)), boot_volume_uuid=self.root)
        tree = read_tree(self.path.read_bytes())
        chosen = tree[('device-tree', 'chosen')]
        self.assertEqual(chosen['osenvironment'], b'recoveryos\0')
        self.assertEqual(chosen['darwinboot-memory-size'], struct.pack('<Q', 0xc0000000))
        self.assertEqual(chosen['embedded-panic-log-size'], struct.pack('<I', 0x80000))
        self.assertEqual(chosen['boot-uuid'], str(self.root).upper().encode() + b'\0')
        self.assertNotIn('platform-uuid', tree[('device-tree', 'options')])
        self.assertEqual(tree[('device-tree', 'product')]['model'], b'xiaomi,sheng\0')


if __name__ == '__main__':
    unittest.main()
