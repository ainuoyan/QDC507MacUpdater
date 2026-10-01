# SPDX-License-Identifier: GPL-3.0-only
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import extract_firmware as tool


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payloads = {'update/boot.bin': b'boot-data',
                         'update/firehose/loader.mbn': b'loader-data'}
        entries = [{'file': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                   for name, data in self.payloads.items()]
        manifest = json.dumps({'loader': entries[1], 'partitions': [entries[0]]}).encode()
        self.payloads['manifest.json'] = manifest
        (self.root / 'firmware').mkdir()
        (self.root / 'firmware/manifest.json').write_bytes(manifest)
        program = bytearray(4096)
        program[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<Q', program, 32, 64)
        struct.pack_into('<HH', program, 54, 56, 1)
        struct.pack_into('<IIQQQQQQ', program, 64, 1, 0, 0, 0x400000, 0, 4096, 4096, 1)
        cursor = 128
        for name, data in self.payloads.items():
            full_name = tool.PREFIX + name.encode()
            name_offset = cursor
            program[cursor:cursor + len(full_name)] = full_name
            cursor += len(full_name) + 1
            descriptor = cursor
            cursor += 32
            program[cursor:cursor + len(data)] = data
            struct.pack_into('<QQQQ', program, descriptor, 0x400000 + name_offset,
                             len(full_name), 0x400000 + cursor, len(data))
            cursor += len(data)
        self.program = self.root / 'manager'
        self.program.write_bytes(program)
        self.output = self.root / 'output'
        self.patches = [patch.object(tool, 'ROOT', self.root),
                        patch.object(tool, 'MANAGER_SIZE', len(program)),
                        patch.object(tool, 'MANAGER_HASH', hashlib.sha256(program).hexdigest()),
                        patch.object(tool, 'MANIFEST_HASH', hashlib.sha256(manifest).hexdigest())]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def extract(self):
        with contextlib.redirect_stdout(io.StringIO()):
            tool.extract(self.program, self.output)

    def test_exact_extraction_and_repeat_preserves_inode(self):
        self.extract()
        for name, data in self.payloads.items():
            self.assertEqual((self.output / name).read_bytes(), data)
        file = self.output / 'update/boot.bin'
        inode = file.stat().st_ino
        self.extract()
        self.assertEqual(file.stat().st_ino, inode)

    def test_wrong_size_is_rejected_before_read(self):
        self.program.write_bytes(b'wrong')
        with patch.object(Path, 'read_bytes') as read, self.assertRaisesRegex(RuntimeError, '大小'):
            self.extract()
        read.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_corrupt_program_is_rejected_without_output(self):
        data = bytearray(self.program.read_bytes()); data[-1] = 1
        self.program.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, 'SHA-256'):
            self.extract()
        self.assertFalse(self.output.exists())

    def test_collision_is_rejected_before_any_output(self):
        file = self.output / 'update/boot.bin'
        file.parent.mkdir(parents=True); file.write_bytes(b'keep')
        with self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
            self.extract()
        self.assertEqual(file.read_bytes(), b'keep')
        self.assertFalse((self.output / 'manifest.json').exists())

    def test_link_failure_leaves_no_partial_file(self):
        with patch.object(tool.os, 'link', side_effect=OSError('disk full')), \
             self.assertRaises(OSError):
            self.extract()
        self.assertFalse(any(p.is_file() for p in self.output.rglob('*')))


if __name__ == '__main__':
    unittest.main()
