# SPDX-License-Identifier: GPL-3.0-only
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import qdc507 as q


class FirmwareTests(unittest.TestCase):
    def test_published_manifest(self):
        path = q.FW / 'manifest.json'
        self.assertEqual(q.digest(path), q.MANIFEST_HASH)
        self.assertEqual(json.loads(path.read_text())['target_firmware'],
                         'QDC507GLEFM21_01.001.02.004')

    @unittest.skipUnless((q.FW / 'update').exists(),
                         '源码包不分发固件；准备 firmware/update 后执行完整文件校验')
    def test_real_bundle(self):
        self.assertEqual(q.manifest()['target_firmware'], 'QDC507GLEFM21_01.001.02.004')

    def test_corrupt_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'manifest.json').write_text('{}')
            with patch.object(q, 'FW', p), self.assertRaisesRegex(RuntimeError, '清单哈希'):
                q.manifest()


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.before = self.folder / 'nand-1.bin'
        self.original = bytes(200)
        self.before.write_bytes(self.original)
        (self.folder / 'nand-2.bin').write_bytes(self.original)
        self.nand = bytearray(self.original)
        self.calls = []
        self.bad_readback = False
        self.damage_protected = False
        self.damage_target = False
        self.parts = {name: (20 + n * 24, 16) for n, name in enumerate(q.PARTITIONS)}
        self.m = {'partitions': [], 'compatibility': [
            {'name': 'SBL', 'offset': 0, 'size': 8, 'sha256': hashlib.sha256(bytes(8)).hexdigest()}]}
        self.saved = {'vid': 0x2c7c, 'pid': 0x0125, 'port': [1, 2], 'bus': 1,
                      'imei': '123456789012345', 'ati': 'Baiwang\nQDC507',
                      'firmware': 'QDC507GLEFM21_01.001.01.009',
                      'usb_config': '+QCFG: "usbcfg",0x2C7C,0x125,1,1,1,1,1,0,0'}
        (self.folder / 'identity.json').write_text(json.dumps(self.saved))
        for n, (name, (start, size)) in enumerate(self.parts.items()):
            content = bytes([n + 1]) * size
            (self.folder / (name + '.bin')).write_bytes(content)
            self.m['partitions'].append({'name': name, 'file': name + '.bin', 'offset': start,
                                        'size': size, 'sha256': hashlib.sha256(content).hexdigest()})
        self.patches = [patch.object(q, 'SIZE', 200), patch.object(q, 'PAGE', 4),
                        patch.object(q, 'PARTITIONS', self.parts), patch.object(q, 'FW', self.folder),
                        patch.object(q, 'manifest', return_value=copy.deepcopy(self.m)),
                        patch.object(q, 'edl', side_effect=self.fake_edl)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def fake_edl(self, m, folder, *args):
        self.calls.append(args)
        if args[0] == 'ws':
            start = args[1] * q.PAGE
            data = args[2].read_bytes()
            self.nand[start:start + len(data)] = data
        elif args[0] == 'rs':
            start, length = args[1] * q.PAGE, args[2] * q.PAGE
            args[3].write_bytes(bytes(length) if self.bad_readback else self.nand[start:start + length])
        elif args[0] == 'rf':
            if self.damage_protected:
                self.nand[0] = 1
            if self.damage_target:
                self.nand[next(iter(self.parts.values()))[0]] = 99
            args[1].write_bytes(self.nand)

    def test_exact_five_partition_plan_and_reset(self):
        q.upgrade(self.m, self.folder, self.before)
        writes = [c for c in self.calls if c[0] == 'ws']
        self.assertEqual([(c[1], c[2].name) for c in writes],
                         [(p['offset'] // 4, p['file']) for p in self.m['partitions']])
        self.assertEqual(self.calls[-1], ('reset',))

    def test_mismatched_backups_no_write(self):
        (self.folder / 'nand-2.bin').write_bytes(b'wrong')
        with self.assertRaisesRegex(RuntimeError, '不一致'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertEqual(self.calls, [])

    def test_incompatible_baseline_no_write(self):
        data = b'x' + self.original[1:]
        self.before.write_bytes(data)
        (self.folder / 'nand-2.bin').write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, '不兼容'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertEqual(self.calls, [])

    def test_truncated_backup_no_write(self):
        self.before.write_bytes(bytes(199))
        with self.assertRaisesRegex(RuntimeError, '128 MiB'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertEqual(self.calls, [])

    def test_bad_readback_stops_before_next_partition(self):
        self.bad_readback = True
        with self.assertRaisesRegex(RuntimeError, '回读失败'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertEqual([c[0] for c in self.calls], ['es', 'ws', 'rs'])

    def test_protected_region_change_no_reset(self):
        self.damage_protected = True
        with self.assertRaisesRegex(RuntimeError, '非目标区域'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertNotIn(('reset',), self.calls)

    def test_later_write_damages_earlier_target_no_reset(self):
        self.damage_target = True
        with self.assertRaisesRegex(RuntimeError, '目标分区'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertNotIn(('reset',), self.calls)

    def test_resumed_backup_rechecks_current_nand(self):
        self.nand[0] = 7
        with self.assertRaisesRegex(RuntimeError, '当前 NAND'):
            q.backup(self.m, self.folder)
        self.assertEqual([c[0] for c in self.calls], ['rf'])

    def test_invalid_identity_never_starts_upgrade(self):
        self.saved.pop('imei')
        (self.folder / 'identity.json').write_text(json.dumps(self.saved))
        with self.assertRaisesRegex(RuntimeError, '身份'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.folder / 'write-started.json').exists())

    def test_marker_sync_failure_never_erases(self):
        with patch.object(q.os, 'fsync', side_effect=OSError('disk full')), self.assertRaises(OSError):
            q.upgrade(self.m, self.folder, self.before)
        self.assertEqual(self.calls, [])

    def test_complete_cli_upgrade_with_simulated_usb(self):
        self.m['target_firmware'] = 'QDC507GLEFM21_01.001.02.004'
        d = SimpleNamespace(idVendor=0x2c7c, idProduct=0x0125, port_numbers=[1, 2], bus=1)
        def enter(device):
            device.idVendor, device.idProduct = 0x05c6, 0x9008
        after = dict(self.saved, firmware=self.m['target_firmware'])
        with patch.object(q, 'ROOT', self.folder), patch.object(q, 'LOCK_FILE', self.folder / 'cli.lock'), \
             patch.object(q.os, 'umask'), patch('sys.argv', ['qdc507.py', 'upgrade']), \
             patch.object(q, 'manifest', return_value=copy.deepcopy(self.m)), \
             patch.object(q, 'device', return_value=d), patch.object(q, 'identity', return_value=self.saved), \
             patch.object(q, 'enter_edl', side_effect=enter), patch.object(q.time, 'sleep'), \
             patch.object(q, 'wait_normal', return_value=after):
            q.main()
        results = list((self.folder / 'sessions').glob('*/result.json'))
        self.assertEqual(len(results), 1)
        result = json.loads(results[0].read_text())
        self.assertTrue(result['verified'])
        self.assertEqual(result['firmware'], self.m['target_firmware'])
        self.assertEqual(self.calls[-1], ('reset',))

    def test_interrupted_upgrade_cannot_resume_as_backup(self):
        (self.folder / 'write-started.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, '禁止'):
            q.backup(self.m, self.folder)
        with self.assertRaisesRegex(RuntimeError, '禁止'):
            q.upgrade(self.m, self.folder, self.before)
        self.assertEqual(self.calls, [])


class RebootTests(unittest.TestCase):
    def check(self, current, expected='target'):
        with patch.object(q.time, 'sleep'), patch.object(q, 'device', return_value=SimpleNamespace(idProduct=0x0125)), \
             patch.object(q, 'identity', return_value=current):
            return q.wait_normal({'imei': 'same'}, expected)

    def test_wrong_version_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, '版本不匹配'):
            self.check({'imei': 'same', 'firmware': 'old'})

    def test_wrong_identity_is_not_success(self):
        with self.assertRaisesRegex(RuntimeError, '身份不一致'):
            self.check({'imei': 'other', 'firmware': 'target'})

    def test_matching_version_and_identity(self):
        current = {'imei': 'same', 'firmware': 'target'}
        self.assertEqual(self.check(current), current)

    def test_changed_usb_config_is_not_success(self):
        current = {'imei': 'same', 'firmware': 'target', 'usb_config': 'changed'}
        with patch.object(q.time, 'sleep'), \
             patch.object(q, 'device', return_value=SimpleNamespace(idProduct=0x0125)), \
             patch.object(q, 'identity', return_value=current), \
             self.assertRaisesRegex(RuntimeError, 'USB'):
            q.wait_normal({'imei': 'same', 'usb_config': 'original'}, 'target')


class EdlExitTests(unittest.TestCase):
    def test_interrupted_child_exits_nonzero(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('review_edl', q.ROOT / 'vendor/edl/edl.py')
        module = importlib.util.module_from_spec(spec)
        with patch('sys.argv', ['edl.py', 'reset']):
            spec.loader.exec_module(module)
        with patch.object(module, 'main') as main, self.assertRaises(SystemExit) as exit_result:
            main.return_value.run.side_effect = KeyboardInterrupt
            module.run()
        self.assertEqual(exit_result.exception.code, 130)


if __name__ == '__main__':
    unittest.main()
