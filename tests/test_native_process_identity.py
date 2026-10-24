# SPDX-License-Identifier: MIT
from pathlib import Path
import struct
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
patch = (ROOT / 'patches/UniXNU/0026-qemu-native-process-identity.patch').read_text()
addition = patch.split('+++ b/scripts/qemu-entry/native_process_identity.py\n', 1)[1]
source = ''.join(line[1:] for line in addition.splitlines(keepends=True)
                 if line.startswith('+') and not line.startswith('+++'))
module = types.ModuleType('native_process_identity')
exec(compile(source, 'native_process_identity.py', 'exec'), module.__dict__)


class NativeProcess(unittest.TestCase):
    def setUp(self):
        self.base = 0xfffffe0008000000
        self.memory = bytearray(0x6000)
        self.thread, self.ro, self.proc, self.proc_ro, self.task, self.upcb = (
            self.base + i * 0x1000 for i in range(6))
        self.plan = dict(kernel_va_bits=47, read_only=True, kernel_sha256='actual',
                         offsets=dict(pid=96, comm=1508),
                         threads=dict(thread_ro=1256, thread_owner=0, thread_proc=24,
                                      thread_task=40, upcb=272, proc_ro=24, proc_owner=0, proc_task=8,
                                      task_shared_region=400, region_slide=4))
        for address, value in ((self.thread + 1256, self.ro), (self.thread + 272, (self.upcb & ((1 << 47) - 1)) | (0x4ef9 << 48)),
                               (self.ro, self.thread), (self.ro + 24, self.proc),
                               (self.ro + 40, self.task), (self.proc + 24, self.proc_ro),
                               (self.proc_ro, self.proc), (self.proc_ro + 8, self.task)):
            struct.pack_into('<Q', self.memory, address - self.base, value)
        struct.pack_into('<I', self.memory, self.proc + 96 - self.base, 88)
        at = self.proc + 1508 - self.base
        self.memory[at:at + 13] = b'WindowServer\0'
        self.calls = []

    def packet(self, request):
        self.assertTrue(request.startswith('m'))
        self.calls.append(request)
        address, size = (int(v, 16) for v in request[1:].split(','))
        self.assertLessEqual(size, 17)
        offset = address - self.base
        return self.memory[offset:offset + size].hex() if 0 <= offset < len(self.memory) else 'E01'

    def test_reads_native_identity_without_changing_guest_state(self):
        before = bytes(self.memory)
        value = module.NativeProcessIdentity(self.plan, 'actual').read(self.packet, self.thread)
        self.assertEqual((value['pid'], value['name'], value['user_state']), (88, 'WindowServer', hex(self.upcb)))
        self.assertEqual(self.memory, before)
        self.assertIsNone(value['shared_region_slide'])

    def test_rejects_wrong_kernel_before_reading(self):
        with self.assertRaisesRegex(ValueError, 'matching'):
            module.NativeProcessIdentity(self.plan, 'different')
        self.assertFalse(self.calls)

    def test_rejects_owner_mismatch_and_non_kernel_pointer(self):
        reader = module.NativeProcessIdentity(self.plan, 'actual')
        struct.pack_into('<Q', self.memory, self.ro - self.base, self.thread + 8)
        with self.assertRaisesRegex(RuntimeError, 'owner mismatch'):
            reader.read(self.packet, self.thread)
        with self.assertRaisesRegex(RuntimeError, 'bounded native'):
            reader.read(self.packet, 0x80000000)


if __name__ == '__main__':
    unittest.main()
