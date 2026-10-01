#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Extract the pinned manager's firmware data without executing its code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MANAGER_HASH = 'c8b0c8192c8f35c81f665711e0331a56e173157f2a9f715024f21ce85e123465'
MANAGER_SIZE = 91529378
MANIFEST_HASH = '2df3c8bc365fd7140ca06c1854e35f7deab7428abd50f85fcdaf4e0ed6b2baab'
PREFIX = b'assets/firmware/qdc507-01.001.02.004/'


def extract(program, output):
    if program.stat().st_size != MANAGER_SIZE:
        raise RuntimeError('管理程序大小不匹配；拒绝读取未知文件')
    data = program.read_bytes()
    if hashlib.sha256(data).hexdigest() != MANAGER_HASH:
        raise RuntimeError('管理程序 SHA-256 不匹配；只接受已记录的 0.1.0 Linux amd64 版本')
    manifest_bytes = (ROOT / 'firmware/manifest.json').read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_HASH:
        raise RuntimeError('仓库固件清单 SHA-256 不匹配')
    manifest = json.loads(manifest_bytes)
    expected = {item['file']: item for item in [manifest['loader']] + manifest['partitions']}
    expected['manifest.json'] = {'size': len(manifest_bytes), 'sha256': MANIFEST_HASH}
    phoff = struct.unpack_from('<Q', data, 32)[0]
    ents, count = struct.unpack_from('<HH', data, 54)
    segments = []
    for i in range(count):
        kind, _, offset, address, _, size, _, _ = struct.unpack_from('<IIQQQQQQ', data, phoff + i * ents)
        if kind == 1:
            segments.append((offset, address, size))

    def file_offset(address, length):
        for offset, start, size in segments:
            if start <= address and address + length <= start + size:
                return offset + address - start
        raise ValueError('数据不在文件映射范围内')

    extracted = {}
    for name, item in expected.items():
        full_name = PREFIX + name.encode()
        start = 0
        while True:
            n = data.find(full_name, start)
            if n < 0:
                break
            start = n + 1
            for offset, address, size in segments:
                if not offset <= n < offset + size:
                    continue
                pointer = struct.pack('<Q', address + n - offset)
                position = 0
                while True:
                    k = data.find(pointer, position)
                    if k < 0:
                        break
                    position = k + 1
                    try:
                        _, name_length, blob_address, length = struct.unpack_from('<QQQQ', data, k)
                        if name_length != len(full_name) or length != item['size']:
                            continue
                        blob_offset = file_offset(blob_address, length)
                        blob = data[blob_offset:blob_offset + length]
                        if len(blob) == length and hashlib.sha256(blob).hexdigest() == item['sha256']:
                            extracted[name] = blob
                    except (ValueError, struct.error):
                        continue
    missing = sorted(set(expected) - set(extracted))
    if missing:
        raise RuntimeError('未找到匹配的内嵌文件: ' + ', '.join(missing))
    for name, blob in extracted.items():
        target = output / name
        if target.exists() and target.read_bytes() != blob:
            raise RuntimeError('目标已有不同内容，拒绝覆盖: ' + str(target))
    for name, blob in extracted.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            print(name, expected[name]['sha256'])
            continue
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
                temporary = Path(out.name)
                out.write(blob)
                out.flush()
                os.fsync(out.fileno())
            # Linking a complete file never truncates an existing destination.
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink()
        print(name, expected[name]['sha256'])
    print('七份文件均已校验并提取；未执行管理程序，未访问 USB。')


def main():
    parser = argparse.ArgumentParser(description='静态提取固定 QDC507 管理程序内嵌固件')
    parser.add_argument('program', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'firmware')
    args = parser.parse_args()
    extract(args.program, args.output)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        print('停止:', error, file=sys.stderr)
        sys.exit(1)
