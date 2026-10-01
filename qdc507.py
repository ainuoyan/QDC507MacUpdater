#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Native QDC507 USB/EDL workflow. Firmware writes require verified fresh backups."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
FW = ROOT / 'firmware'
MANIFEST_HASH = '2df3c8bc365fd7140ca06c1854e35f7deab7428abd50f85fcdaf4e0ed6b2baab'
SIZE = 134217728
PAGE = 2048
PARTITIONS = {'RAWDATA': (23855104, 524288), 'aboot': (27787264, 1310720),
              'boot': (29097984, 5636096), 'recoveryfs': (35258368, 5505024),
              'system': (62783488, 71434240)}
IDS = {(0x2c7c, 0x0125), (0x2ca3, 0x4006), (0x05c6, 0x9008)}
LOCK_FILE = Path(tempfile.gettempdir()) / ('qdc507-' + str(os.getuid()) + '.lock')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def manifest():
    p = FW / 'manifest.json'
    if digest(p) != MANIFEST_HASH:
        raise RuntimeError('固件清单哈希不匹配')
    m = json.loads(p.read_text())
    if (m['model'] != 'QDC507' or
        m['geometry'] != {'page_size': PAGE, 'pages_per_block': 64, 'total_blocks': 1024} or
        {p['name']: (p['offset'], p['size']) for p in m['partitions']} != PARTITIONS):
        raise RuntimeError('固件型号、几何参数或写入范围不匹配')
    for item in [m['loader']] + m['partitions']:
        p = FW / item['file']
        if p.stat().st_size != item['size'] or digest(p) != item['sha256']:
            raise RuntimeError('固件文件校验失败: ' + item['file'])
    return m


def device():
    import usb.core
    import usb.backend.libusb1
    library = next((p for p in ('/opt/homebrew/lib/libusb-1.0.dylib',
                                '/usr/local/lib/libusb-1.0.dylib') if Path(p).exists()), None)
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: library)
    if backend is None:
        raise RuntimeError('找不到 Homebrew libusb')
    devices = [d for d in usb.core.find(find_all=True, backend=backend)
               if (d.idVendor, d.idProduct) in IDS]
    if len(devices) != 1:
        raise RuntimeError('需要且只能连接一个 QDC507/9008，当前数量: ' + str(len(devices)))
    return devices[0]


@contextlib.contextmanager
def interface(d, number):
    import usb.util
    cfg = d.get_active_configuration()
    itf = cfg[(number, 0)]
    if itf.bInterfaceClass != 255:
        raise RuntimeError('接口类型不匹配')
    ins = [e for e in itf if e.bmAttributes & 3 == 2 and e.bEndpointAddress & 128]
    outs = [e for e in itf if e.bmAttributes & 3 == 2 and not e.bEndpointAddress & 128]
    if len(ins) != 1 or len(outs) != 1:
        raise RuntimeError('USB bulk 端点布局不匹配')
    usb.util.claim_interface(d, number)
    try:
        yield ins[0], outs[0]
    finally:
        usb.util.release_interface(d, number)
        usb.util.dispose_resources(d)


def identity(d):
    import usb.core
    if d.idProduct == 0x9008:
        raise RuntimeError('已处于 9008；需要本工具先前记录的原始身份')
    result = {'vid': d.idVendor, 'pid': d.idProduct, 'port': list(d.port_numbers or []),
              'bus': getattr(d, 'bus', None)}
    with interface(d, 2) as (rx, tx):
        for key, cmd in [('ati', 'ATI'), ('firmware', 'AT+QGMR'), ('imei', 'AT+GSN'),
                         ('usb_config', 'AT+QCFG="usbcfg"')]:
            drain_deadline = time.monotonic() + 1
            while time.monotonic() < drain_deadline:
                try:
                    rx.read(4096, timeout=100)
                except usb.core.USBTimeoutError:
                    break
            else:
                raise RuntimeError('无法清理 AT 旧响应，停止操作')
            payload = (cmd + '\r').encode()
            if tx.write(payload, timeout=2000) != len(payload):
                raise RuntimeError('AT 请求 USB 短写，停止操作')
            buf = b''
            end = time.monotonic() + 6
            while time.monotonic() < end:
                try:
                    buf += bytes(rx.read(4096, timeout=500))
                except usb.core.USBTimeoutError:
                    continue
                if b'\r\nOK\r\n' in buf or b'ERROR' in buf:
                    break
            if b'\r\nOK\r\n' not in buf:
                raise RuntimeError('AT 请求失败: ' + cmd)
            lines = [s.strip() for s in buf.decode(errors='replace').splitlines()]
            lines = [s for s in lines if s and s not in (cmd, 'OK') and
                     (not s.startswith('+') or (key == 'usb_config' and s.startswith('+QCFG:')))]
            result[key] = '\n'.join(lines)
    if 'QDC507' not in result['ati'] or not result['firmware'].startswith('QDC507GLEFM21'):
        raise RuntimeError('不是目标型号，停止操作')
    validate_identity(result)
    return result


def validate_identity(saved):
    if (not isinstance(saved, dict) or
        (saved.get('vid'), saved.get('pid')) not in IDS - {(0x05c6, 0x9008)} or
        not isinstance(saved.get('imei'), str) or not re.fullmatch(r'[0-9]{15}', saved['imei']) or
        not isinstance(saved.get('firmware'), str) or
        not re.fullmatch(r'QDC507GLEFM21_[A-Za-z0-9_.]+', saved['firmware']) or
        not isinstance(saved.get('ati'), str) or 'QDC507' not in saved['ati'] or
        not isinstance(saved.get('usb_config'), str) or '"usbcfg"' not in saved['usb_config'] or
        not isinstance(saved.get('port'), list) or not saved['port'] or
        any(type(port) is not int or port <= 0 for port in saved['port']) or
        (saved.get('bus') is not None and (type(saved['bus']) is not int or saved['bus'] < 0))):
        raise RuntimeError('身份记录不完整或异常，禁止继续；需要有效 IMEI、固件和 USB 端口')


def load_identity(folder):
    try:
        saved = json.loads((folder / 'identity.json').read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError('无法读取有效身份记录，禁止继续') from error
    validate_identity(saved)
    return saved


def write_json(path, value):
    # Persist the marker before any erase, and never replace an existing task file.
    with path.open('x') as out:
        json.dump(value, out, indent=2)
        out.flush()
        os.fsync(out.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def enter_edl(d):
    with interface(d, 0) as (_, tx):
        # Quectel QFirehose emergency-download command; no NAND write.
        payload = bytes.fromhex('4b650100540f7e')
        if tx.write(payload, timeout=2000) != len(payload):
            raise RuntimeError('EDL 请求 USB 短写，停止操作')


def wait_normal(saved, expected=None):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            d = device()
            if d.idProduct == 0x9008:
                continue
            current = identity(d)
        except (RuntimeError, OSError):
            continue
        if current['imei'] != saved['imei']:
            raise RuntimeError('复位后身份不一致')
        if expected and current['firmware'] != expected:
            raise RuntimeError('复位后固件版本不匹配: ' + current['firmware'])
        for key in ('vid', 'pid', 'port', 'usb_config', 'bus'):
            if saved.get(key) is not None and current.get(key) != saved[key]:
                raise RuntimeError('复位后 USB 身份或配置不一致: ' + key)
        print('复位后 AT 验证通过，固件:', current['firmware'], flush=True)
        return current
    raise RuntimeError('复位后等待期限内未恢复 AT 通信；请检查 USB，升级未确认成功')


def edl(m, folder, *args):
    d = device()
    if (d.idVendor, d.idProduct) != (0x05c6, 0x9008):
        raise RuntimeError('需要 05c6:9008 下载模式')
    saved = load_identity(folder)
    if list(d.port_numbers or []) != saved['port']:
        raise RuntimeError('USB 物理端口变更，无法确认同一设备')
    if saved.get('bus') is not None and d.bus != saved['bus']:
        raise RuntimeError('USB 总线变更，无法确认同一设备')
    cmd = [sys.executable, str(ROOT / 'vendor/edl/edl.py'), *map(str, args),
           '--vid=0x05c6', '--pid=0x9008', '--memory=NAND', '--pagesperblock=64',
           '--loader=' + str(FW / m['loader']['file'])]
    if args[0] in ('rf', 'rs', 'ws', 'es', 'reset'):
        cmd.append('--sectorsize=2048')
    log = folder / (str(time.time_ns()) + '-' + args[0] + '.log')
    print('EDL:', args[0], '日志:', log, flush=True)
    env = dict(os.environ, DYLD_FALLBACK_LIBRARY_PATH='/opt/homebrew/lib:/usr/local/lib:/usr/lib')
    with log.open('wb') as out:
        try:
            r = subprocess.run(cmd, cwd=folder, env=env, stdout=out,
                               stderr=subprocess.STDOUT, timeout=600)
        except subprocess.TimeoutExpired:
            raise RuntimeError('EDL 超时；保留连接与日志，不自动重启: ' + str(log)) from None
    if r.returncode:
        raise RuntimeError('EDL 执行失败，查看 ' + str(log))


def validate_backup(path, m):
    if path.stat().st_size != SIZE:
        raise RuntimeError('完整备份不是 128 MiB，停止操作')
    with path.open('rb') as f:
        for region in m['compatibility']:
            f.seek(region['offset'])
            if hashlib.sha256(f.read(region['size'])).hexdigest() != region['sha256']:
                raise RuntimeError('硬件/分区基线不兼容: ' + region['name'])


def backup(m, folder):
    if folder.joinpath('write-started.json').exists():
        raise RuntimeError('此任务已尝试写入，禁止把修改后的 NAND 当原始备份')
    first, second = folder / 'nand-1.bin', folder / 'nand-2.bin'
    reused = first.exists() and second.exists()
    for path in (first, second):
        if path.exists():
            if path.stat().st_size != SIZE:
                raise RuntimeError('已有不完整备份，保留现场；使用新任务目录')
            continue
        partial = path.with_suffix('.partial')
        if partial.exists():
            raise RuntimeError('已有中断读取文件，保留现场；使用新任务目录')
        edl(m, folder, 'rf', partial)
        if partial.stat().st_size != SIZE:
            raise RuntimeError('备份大小异常，停止操作')
        partial.rename(path)
        if path.stat().st_size != SIZE:
            raise RuntimeError('备份大小异常，停止操作')
    if digest(first) != digest(second):
        raise RuntimeError('两份备份不一致，禁止升级')
    validate_backup(first, m)
    if reused:
        current = folder / 'nand-current.partial'
        if current.exists():
            raise RuntimeError('已有当前 NAND 中断读取文件，保留现场')
        edl(m, folder, 'rf', current)
        if current.stat().st_size != SIZE or digest(current) != digest(first):
            raise RuntimeError('当前 NAND 与原备份不同，禁止复用旧任务升级')
        current.unlink()
    print('双份完整备份及兼容性校验通过:', digest(first), flush=True)
    return first


def upgrade(m, folder, before):
    # Recheck the gates here, so no caller can bypass them.
    if manifest() != m:
        raise RuntimeError('升级前固件清单发生变化')
    load_identity(folder)
    validate_backup(before, m)
    if digest(before) != digest(folder / 'nand-2.bin'):
        raise RuntimeError('两份备份不一致，禁止升级')
    if folder.joinpath('write-started.json').exists():
        raise RuntimeError('此任务已尝试写入，禁止自动再次升级；保留备份和日志')
    write_json(folder / 'write-started.json', {'at': time.time()})
    for p in m['partitions']:
        edl(m, folder, 'es', p['offset'] // PAGE, p['size'] // PAGE)
        edl(m, folder, 'ws', p['offset'] // PAGE, FW / p['file'])
        readback = folder / (p['name'] + '-readback.bin')
        edl(m, folder, 'rs', p['offset'] // PAGE, p['size'] // PAGE, readback)
        if readback.stat().st_size != p['size'] or digest(readback) != p['sha256']:
            raise RuntimeError('刷后回读失败: ' + p['name'] + '；保留连接，不自动重启')
    after = folder / 'nand-after.bin'
    edl(m, folder, 'rf', after)
    if after.stat().st_size != SIZE:
        raise RuntimeError('刷后全盘回读大小不匹配')
    with before.open('rb') as a, after.open('rb') as b:
        ranges = sorted(PARTITIONS.values())
        position = 0
        for start, size in ranges + [(SIZE, 0)]:
            a.seek(position); b.seek(position)
            while position < start:
                n = min(1024 * 1024, start - position)
                if a.read(n) != b.read(n):
                    raise RuntimeError('非目标区域发生变化，保留连接，不自动重启')
                position += n
            if size:
                b.seek(start)
                checksum = hashlib.sha256()
                remaining = size
                while remaining:
                    data = b.read(min(1024 * 1024, remaining))
                    if not data:
                        raise RuntimeError('全盘回读目标分区截断，禁止复位')
                    checksum.update(data)
                    remaining -= len(data)
                target = next(p for p in m['partitions'] if p['offset'] == start)
                if checksum.hexdigest() != target['sha256']:
                    raise RuntimeError('全盘回读目标分区不匹配: ' + target['name'] + '，禁止复位')
            position = start + size
    print('五区回读及非目标区域校验通过。执行复位。', flush=True)
    edl(m, folder, 'reset')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description='QDC507 Mac 原生备份/升级工具')
    parser.add_argument('command', choices=['inspect', 'verify-firmware', 'backup', 'upgrade'])
    parser.add_argument('--session', type=Path, help='重连后继续同一任务的目录')
    args = parser.parse_args()
    if args.command == 'verify-firmware':
        m = manifest()
        print('固件及加载器校验通过:', m['target_firmware'])
        return
    ROOT.joinpath('sessions').mkdir(mode=0o700, exist_ok=True)
    with LOCK_FILE.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('已有 QDC507 任务正在运行；不同工具目录也不能并行') from None
        d = device()
        if args.command == 'inspect':
            print('USB: %04x:%04x' % (d.idVendor, d.idProduct))
            if d.idProduct != 0x9008:
                i = identity(d)
                print('型号: QDC507\n固件:', i['firmware'])
            else:
                print('EDL 配置描述符:', d.get_active_configuration().bNumInterfaces, '个接口')
            return
        m = manifest()
        folder = args.session.resolve() if args.session else ROOT / 'sessions' / time.strftime('%Y%m%d-%H%M%S')
        folder.mkdir(mode=0o700, exist_ok=True)
        if (folder / 'result.json').exists():
            raise RuntimeError('任务已完成，禁止复用；请使用新任务目录')
        if shutil.disk_usage(folder).free < SIZE * 5:
            raise RuntimeError('任务目录所在磁盘至少需要 640 MiB 空闲空间')
        statefile = folder / 'identity.json'
        if d.idProduct != 0x9008:
            if statefile.exists():
                raise RuntimeError('普通模式使用新任务目录；已有任务不可覆盖')
            current = identity(d)
            if args.command == 'upgrade' and current['firmware'] == m['target_firmware']:
                print('已是目标固件，无需重复刷写。')
                return
            write_json(statefile, current)
            print('身份已保存。正在切换 EDL。任务目录:', folder, flush=True)
            enter_edl(d)
            for _ in range(30):
                time.sleep(1)
                try:
                    d = device()
                    if d.idProduct == 0x9008:
                        break
                except RuntimeError:
                    continue
        if d.idProduct != 0x9008 or not statefile.exists():
            raise RuntimeError('未发现 9008 或缺少本次身份记录；重连后使用 --session ' + str(folder))
        saved = load_identity(folder)
        if list(d.port_numbers or []) != saved['port']:
            raise RuntimeError('USB 物理端口变更，无法确认同一设备')
        if saved.get('bus') is not None and d.bus != saved['bus']:
            raise RuntimeError('USB 总线变更，无法确认同一设备')
        before = backup(m, folder)
        if args.command == 'upgrade':
            upgrade(m, folder, before)
        else:
            edl(m, folder, 'reset')
        current = wait_normal(saved, m['target_firmware'] if args.command == 'upgrade' else saved['firmware'])
        write_json(folder / 'result.json', {
            'command': args.command, 'verified': True, 'firmware': current['firmware'],
            'backup_sha256': digest(before), 'completed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')})
        print('任务完成。日志和备份:', folder)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, AssertionError) as e:
        print('停止:', e, file=sys.stderr)
        sys.exit(1)
