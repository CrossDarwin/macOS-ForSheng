# SPDX-License-Identifier: MIT
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from native_devtree import configure_native_text_state


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


class NativeTree(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'kernel.adt'
        self.path.write_bytes(node('device-tree', children=(node('chosen'), node('options'))))
        self.root = uuid.UUID('808eac5e-8275-478d-814c-2229d8eb8d07')
        self.vm = uuid.UUID('7e8b064b-8ddb-54c4-b332-6fe0c34f937c')

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
        self.assertEqual(tree[('device-tree', 'chosen', 'secure-boot-hashes')]['system-volume-auth-blob'], bytes(range(32)))
        configure_native_text_state(self.path, **options)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'conflicts'):
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

    def test_missing_options_is_refused_without_rewriting_tree(self):
        before = node('device-tree', children=(node('chosen'),))
        self.path.write_bytes(before)
        with self.assertRaisesRegex(ValueError, 'complete generated'):
            configure_native_text_state(self.path, development_root=True, platform_uuid=self.vm)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
