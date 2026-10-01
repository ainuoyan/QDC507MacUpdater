# SPDX-License-Identifier: GPL-3.0-only
import contextlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import usb.core

import qdc507 as q


class UsbWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.lock_patch = patch.object(q, 'LOCK_FILE', self.folder / 'shared.lock')
        self.lock_patch.start()
        self.saved = {'vid': 0x2c7c, 'pid': 0x0125, 'port': [1, 2], 'bus': 1,
                      'imei': '123456789012345', 'ati': 'Baiwang\nQDC507',
                      'firmware': 'QDC507GLEFM21_01.001.01.009',
                      'usb_config': '+QCFG: "usbcfg",0x2C7C,0x125,1,1,1,1,1,0,0'}
        (self.folder / 'identity.json').write_text(json.dumps(self.saved))

    def tearDown(self):
        self.lock_patch.stop()
        self.temp.cleanup()

    def test_edl_wrong_port_never_starts_subprocess(self):
        d = SimpleNamespace(idVendor=0x05c6, idProduct=0x9008, port_numbers=[3], bus=1)
        with patch.object(q, 'device', return_value=d), \
             patch.object(q.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            with self.assertRaisesRegex(RuntimeError, '端口'):
                q.edl({'loader': {'file': 'unused'}}, self.folder, 'reset')
            run.assert_not_called()

    def test_edl_wrong_bus_never_starts_subprocess(self):
        d = SimpleNamespace(idVendor=0x05c6, idProduct=0x9008, port_numbers=[1, 2], bus=2)
        with patch.object(q, 'device', return_value=d), \
             patch.object(q.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            with self.assertRaisesRegex(RuntimeError, '总线'):
                q.edl({'loader': {'file': 'unused'}}, self.folder, 'reset')
            run.assert_not_called()

    def test_edl_request_short_write_is_failure(self):
        tx = SimpleNamespace(write=Mock(return_value=3))
        @contextlib.contextmanager
        def fake_interface(*args):
            yield None, tx
        with patch.object(q, 'interface', fake_interface), self.assertRaisesRegex(RuntimeError, '短写'):
            q.enter_edl(object())

    def test_inspect_works_without_firmware_files(self):
        d = SimpleNamespace(idVendor=0x2c7c, idProduct=0x0125)
        with patch.object(q, 'ROOT', self.folder), patch.object(q.os, 'umask'), \
             patch('sys.argv', ['qdc507.py', 'inspect']), \
             patch.object(q, 'manifest', side_effect=AssertionError('inspect 不应读取固件')), \
             patch.object(q, 'device', return_value=d), patch.object(q, 'identity', return_value=self.saved):
            q.main()

    def identity_endpoints(self, stale=False, imei='123456789012345', short=False):
        replies = {'ATI': 'Baiwang\r\nQDC507',
                   'AT+QGMR': self.saved['firmware'], 'AT+GSN': imei,
                   'AT+QCFG="usbcfg"': self.saved['usb_config']}
        queue = [b'\r\nOK\r\n'] if stale else []
        def write(data, **kwargs):
            if short:
                return len(data) - 1
            queue.append(('\r\n' + replies[data.decode().strip()] + '\r\nOK\r\n').encode())
            return len(data)
        def read(*args, **kwargs):
            if queue:
                return queue.pop(0)
            raise usb.core.USBTimeoutError('empty')
        rx, tx = SimpleNamespace(read=read), SimpleNamespace(write=write)
        @contextlib.contextmanager
        def fake_interface(*args):
            yield rx, tx
        return fake_interface

    def test_stale_at_ok_is_drained_before_query(self):
        d = SimpleNamespace(idVendor=0x2c7c, idProduct=0x0125, port_numbers=[1, 2], bus=1)
        with patch.object(q, 'interface', self.identity_endpoints(stale=True)):
            self.assertEqual(q.identity(d)['imei'], self.saved['imei'])

    def test_at_short_write_stops_identity_query(self):
        d = SimpleNamespace(idVendor=0x2c7c, idProduct=0x0125, port_numbers=[1, 2], bus=1)
        with patch.object(q, 'interface', self.identity_endpoints(short=True)), \
             self.assertRaisesRegex(RuntimeError, '短写'):
            q.identity(d)

    def test_invalid_at_imei_is_rejected(self):
        d = SimpleNamespace(idVendor=0x2c7c, idProduct=0x0125, port_numbers=[1, 2], bus=1)
        with patch.object(q, 'interface', self.identity_endpoints(imei='missing')), \
             self.assertRaisesRegex(RuntimeError, '身份'):
            q.identity(d)

    def test_persistent_marker_is_exclusive(self):
        path = self.folder / 'write-started.json'
        q.write_json(path, {'first': True})
        with self.assertRaises(FileExistsError):
            q.write_json(path, {'second': True})
        self.assertEqual(json.loads(path.read_text()), {'first': True})

    def test_session_volume_is_checked_before_edl(self):
        m = {'target_firmware': 'QDC507GLEFM21_01.001.02.004'}
        task = self.folder / 'external-volume-task'
        d = SimpleNamespace(idVendor=0x2c7c, idProduct=0x0125)
        with patch.object(q, 'ROOT', self.folder), patch.object(q.os, 'umask'), \
             patch('sys.argv', ['qdc507.py', 'upgrade', '--session', str(task)]), \
             patch.object(q, 'manifest', return_value=m), patch.object(q, 'device', return_value=d), \
             patch.object(q.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)) as usage, \
             patch.object(q, 'enter_edl') as enter:
            with self.assertRaisesRegex(RuntimeError, '任务目录'):
                q.main()
            usage.assert_called_once_with(task.resolve())
            enter.assert_not_called()

    def test_other_checkout_cannot_use_usb_while_locked(self):
        other = self.folder / 'other-checkout'; other.mkdir()
        with q.LOCK_FILE.open('a') as first:
            q.fcntl.flock(first, q.fcntl.LOCK_EX | q.fcntl.LOCK_NB)
            with patch.object(q, 'ROOT', other), patch.object(q.os, 'umask'), \
                 patch('sys.argv', ['qdc507.py', 'inspect']), patch.object(q, 'device') as device:
                with self.assertRaisesRegex(RuntimeError, '正在运行'):
                    q.main()
                device.assert_not_called()

    def test_completed_task_is_rejected_before_backup(self):
        (self.folder / 'result.json').write_text('{}')
        d = SimpleNamespace(idVendor=0x05c6, idProduct=0x9008)
        with patch.object(q, 'ROOT', self.folder), patch.object(q.os, 'umask'), \
             patch('sys.argv', ['qdc507.py', 'backup', '--session', str(self.folder)]), \
             patch.object(q, 'manifest', return_value={}), patch.object(q, 'device', return_value=d), \
             patch.object(q, 'backup') as backup, self.assertRaisesRegex(RuntimeError, '任务已完成'):
            q.main()
        backup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
