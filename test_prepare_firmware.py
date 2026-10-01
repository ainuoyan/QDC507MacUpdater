# SPDX-License-Identifier: GPL-3.0-only
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from tools import prepare_firmware as tool


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root / '.firmware-cache'
        self.cache.mkdir()
        self.program = b'pinned-manager'
        self.files = {'update/boot.bin': b'boot', 'update/firehose/loader.mbn': b'loader'}
        entries = [{'file': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                   for name, data in self.files.items()]
        manifest = json.dumps({'loader': entries[1], 'partitions': [entries[0]]}).encode()
        (self.root / 'firmware').mkdir()
        (self.root / 'firmware/manifest.json').write_bytes(manifest)
        self.patches = [patch.object(tool.firmware, 'ROOT', self.root),
                        patch.object(tool.firmware, 'MANIFEST_HASH', hashlib.sha256(manifest).hexdigest()),
                        patch.object(tool.firmware, 'MANAGER_SIZE', len(self.program)),
                        patch.object(tool.firmware, 'MANAGER_HASH', hashlib.sha256(self.program).hexdigest()),
                        contextlib.redirect_stdout(io.StringIO())]
        for item in self.patches:
            item.__enter__()

    def tearDown(self):
        for item in reversed(self.patches):
            item.__exit__(None, None, None)
        self.temp.cleanup()

    def layer(self, payload=None, symlink=False):
        data = io.BytesIO()
        payload = self.program if payload is None else payload
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            member = tarfile.TarInfo(tool.MEMBER)
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = '/etc/passwd'
                archive.addfile(member)
            else:
                member.size = len(payload)
                archive.addfile(member, io.BytesIO(payload))
            other = tarfile.TarInfo('../outside.bin')
            other.size = 4
            archive.addfile(other, io.BytesIO(b'keep'))
        return data.getvalue()

    def download(self, data, response=None):
        with patch.object(tool, 'LAYER_SIZE', len(data)), \
             patch.object(tool, 'LAYER_HASH', hashlib.sha256(data).hexdigest()), \
             patch.object(tool, 'open_url', side_effect=[io.BytesIO(b'{"token":"temporary-token"}'),
                                                        response or io.BytesIO(data)]) as opened:
            result = tool.prepare_manager(self.cache)
        return result, opened

    def test_complete_firmware_skips_network_and_preserves_files(self):
        for name, data in self.files.items():
            path = self.root / 'firmware' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        inode = (self.root / 'firmware/update/boot.bin').stat().st_ino
        with patch.object(tool, 'open_url') as opened, patch.object(tool, 'prepare_manager') as manager:
            tool.main()
        opened.assert_not_called()
        manager.assert_not_called()
        self.assertEqual((self.root / 'firmware/update/boot.bin').stat().st_ino, inode)

    def test_missing_firmware_uses_verified_manager_and_extractor(self):
        path = self.cache / 'dji-fw-manager'
        with patch.object(tool, 'prepare_manager', return_value=path) as manager, \
             patch.object(tool.firmware, 'extract') as extract:
            tool.main()
        manager.assert_called_once_with(self.cache)
        extract.assert_called_once_with(path, self.root / 'firmware')

    def test_corrupt_existing_firmware_stops_before_network(self):
        path = self.root / 'firmware/update/boot.bin'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'wrong')
        with patch.object(tool, 'open_url') as opened, self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
            tool.main()
        opened.assert_not_called()
        self.assertEqual(path.read_bytes(), b'wrong')

    def test_modified_manifest_stops_before_network(self):
        (self.root / 'firmware/manifest.json').write_text('{}')
        with patch.object(tool, 'open_url') as opened, self.assertRaisesRegex(RuntimeError, '清单'):
            tool.main()
        opened.assert_not_called()

    def test_valid_cache_is_reused_without_network(self):
        path = self.cache / 'dji-fw-manager'
        path.write_bytes(self.program)
        inode = path.stat().st_ino
        with patch.object(tool, 'open_url') as opened:
            self.assertEqual(tool.prepare_manager(self.cache), path)
        opened.assert_not_called()
        self.assertEqual(path.stat().st_ino, inode)

    def test_corrupt_cache_is_not_overwritten(self):
        path = self.cache / 'dji-fw-manager'
        path.write_bytes(b'wrong')
        with patch.object(tool, 'open_url') as opened, self.assertRaisesRegex(RuntimeError, '缓存校验失败'):
            tool.prepare_manager(self.cache)
        opened.assert_not_called()
        self.assertEqual(path.read_bytes(), b'wrong')

    def test_download_validates_and_only_copies_expected_regular_file(self):
        path, opened = self.download(self.layer())
        self.assertEqual(path.read_bytes(), self.program)
        self.assertEqual(list(self.cache.iterdir()), [path])
        self.assertFalse((self.root / 'outside.bin').exists())
        calls = opened.call_args_list
        self.assertIn('auth.docker.io/token?', calls[0].args[0])
        self.assertIn('/blobs/sha256:', calls[1].args[0])
        self.assertEqual(calls[1].args[1], {'Authorization': 'Bearer temporary-token'})

    def test_bad_layer_hash_leaves_no_manager_or_download_folder(self):
        data = self.layer()
        with patch.object(tool, 'LAYER_SIZE', len(data)), patch.object(tool, 'LAYER_HASH', '0' * 64), \
             patch.object(tool, 'open_url', side_effect=[io.BytesIO(b'{"token":"t"}'), io.BytesIO(data)]), \
             self.assertRaisesRegex(RuntimeError, 'SHA-256'):
            tool.prepare_manager(self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_oversized_download_is_rejected_and_cleaned(self):
        data = self.layer()
        with patch.object(tool, 'LAYER_SIZE', len(data) - 1), \
             patch.object(tool, 'open_url', side_effect=[io.BytesIO(b'{"token":"t"}'), io.BytesIO(data)]), \
             self.assertRaisesRegex(RuntimeError, '超过固定大小'):
            tool.prepare_manager(self.cache)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_truncated_download_is_rejected_and_cleaned(self):
        data = self.layer()
        with self.assertRaisesRegex(RuntimeError, '下载不完整'):
            self.download(data, io.BytesIO(data[:-1]))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_network_error_is_cleaned(self):
        class Interrupted(io.BytesIO):
            def read(self, size=-1):
                raise OSError('connection lost')
        with self.assertRaisesRegex(OSError, 'connection lost'):
            self.download(self.layer(), Interrupted(b'data'))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_program_symlink_is_rejected_and_cleaned(self):
        with self.assertRaisesRegex(RuntimeError, '类型或大小'):
            self.download(self.layer(symlink=True))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_wrong_program_hash_is_rejected_and_cleaned(self):
        with self.assertRaisesRegex(RuntimeError, '缓存校验失败'):
            self.download(self.layer(b'X' * len(self.program)))
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_invalid_auth_response_creates_no_files(self):
        for data in [b'[]', b'{"token":""}', b'x' * 65537]:
            with self.subTest(data=data[:20]), patch.object(tool, 'open_url', return_value=io.BytesIO(data)), \
                 self.assertRaises(RuntimeError):
                tool.prepare_manager(self.cache)
            self.assertEqual(list(self.cache.iterdir()), [])


class RedirectTests(unittest.TestCase):
    def setUp(self):
        self.request = urllib.request.Request('https://registry.example/blob',
                                              headers={'Authorization': 'Bearer token'})

    def redirect(self, url):
        return tool.HTTPSRedirect().redirect_request(self.request, None, 307, 'redirect', {}, url)

    def test_cross_host_redirect_does_not_forward_token(self):
        self.assertIsNone(self.redirect('https://cdn.example/blob').get_header('Authorization'))

    def test_same_host_redirect_preserves_token(self):
        self.assertEqual(self.redirect('https://registry.example/other').get_header('Authorization'),
                         'Bearer token')

    def test_http_redirect_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '非 HTTPS'):
            self.redirect('http://cdn.example/blob')


if __name__ == '__main__':
    unittest.main()
