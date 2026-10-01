#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Prepare pinned firmware from its public source without Docker or USB access."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request

from . import extract_firmware as firmware

REPOSITORY = 'canghaiwuhen/dji-qdc507-firmware-manager'
LAYER_HASH = '3eb0f67192fcf4e29c41f3d1740266d35c963192e41fbecc99ac0169deab4ddf'
LAYER_SIZE = 57404289
MEMBER = 'app/dji-fw-manager'


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise RuntimeError('拒绝跳转到非 HTTPS 下载地址')
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(request.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header('Authorization')
        return redirected


def open_url(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    return urllib.request.build_opener(HTTPSRedirect()).open(request, timeout=60)


def download_layer(path):
    query = urllib.parse.urlencode({'service': 'registry.docker.io',
                                   'scope': 'repository:' + REPOSITORY + ':pull'})
    with open_url('https://auth.docker.io/token?' + query) as response:
        data = response.read(65537)
    if len(data) > 65536:
        raise RuntimeError('镜像源认证响应过大')
    credentials = json.loads(data)
    token = credentials.get('token') if isinstance(credentials, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError('镜像源没有返回有效下载凭据')
    url = 'https://registry-1.docker.io/v2/' + REPOSITORY + '/blobs/sha256:' + LAYER_HASH
    print('从原作者镜像下载所需数据，约 55 MiB；无需 Docker。', flush=True)
    total = 0
    next_progress = 10 * 1024 * 1024
    with open_url(url, {'Authorization': 'Bearer ' + token}) as response, path.open('xb') as out:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > LAYER_SIZE:
                raise RuntimeError('下载数据超过固定大小，停止')
            out.write(block)
            if total >= next_progress:
                print('已下载 %.1f / %.1f MiB' % (total / 1048576, LAYER_SIZE / 1048576), flush=True)
                next_progress += 10 * 1024 * 1024
    if total != LAYER_SIZE or digest(path) != LAYER_HASH:
        raise RuntimeError('下载不完整或镜像层 SHA-256 不匹配，请重新运行')


def validate_manager(path):
    if path.stat().st_size != firmware.MANAGER_SIZE or digest(path) != firmware.MANAGER_HASH:
        raise RuntimeError('管理程序缓存校验失败；请删除 .firmware-cache/dji-fw-manager 后重新运行')


def prepare_manager(cache):
    manager = cache / 'dji-fw-manager'
    if manager.exists():
        validate_manager(manager)
        return manager
    with tempfile.TemporaryDirectory(prefix='download-', dir=cache) as folder:
        folder = Path(folder)
        layer = folder / 'layer.tar.gz'
        download_layer(layer)
        temporary = folder / 'dji-fw-manager'
        with tarfile.open(layer, mode='r:gz') as archive:
            try:
                member = archive.getmember(MEMBER)
            except KeyError:
                raise RuntimeError('镜像层缺少预期的管理程序') from None
            if not member.isfile() or member.size != firmware.MANAGER_SIZE:
                raise RuntimeError('镜像层中的管理程序类型或大小不匹配')
            with archive.extractfile(member) as source, temporary.open('xb') as out:
                shutil.copyfileobj(source, out)
                out.flush()
                os.fsync(out.fileno())
        validate_manager(temporary)
        try:
            os.link(temporary, manager)
        except FileExistsError:
            # A concurrent preparation may have finished; never overwrite its file.
            validate_manager(manager)
    return manager


def main():
    output = firmware.ROOT / 'firmware'
    manifest_data = (output / 'manifest.json').read_bytes()
    if hashlib.sha256(manifest_data).hexdigest() != firmware.MANIFEST_HASH:
        raise RuntimeError('固件清单 SHA-256 不匹配')
    manifest = json.loads(manifest_data)
    missing = False
    for item in [manifest['loader']] + manifest['partitions']:
        path = output / item['file']
        if not path.exists():
            missing = True
        elif path.stat().st_size != item['size'] or digest(path) != item['sha256']:
            raise RuntimeError('已有固件内容不匹配，拒绝覆盖: ' + item['file'])
    if not missing:
        print('固件和加载器已完整校验，无需再次下载。')
        return
    cache = firmware.ROOT / '.firmware-cache'
    cache.mkdir(mode=0o700, exist_ok=True)
    manager = prepare_manager(cache)
    firmware.extract(manager, output)
    print('固件准备完成。接下来运行 ./setup.sh，再使用 ./qdc507 inspect 检查模块。')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, tarfile.TarError, http.client.HTTPException) as error:
        print('停止:', error, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('已取消；没有访问 USB 或刷写模块。', file=sys.stderr)
        sys.exit(130)
