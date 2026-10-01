#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
  echo '此入口用于 macOS。' >&2
  exit 1
fi
if [[ ! -f /opt/homebrew/lib/libusb-1.0.dylib && ! -f /usr/local/lib/libusb-1.0.dylib ]]; then
  echo '缺少 libusb，请先安装 Homebrew，然后执行 brew install libusb。' >&2
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [[ -d firmware/update ]]; then
  .venv/bin/python qdc507.py verify-firmware
else
  echo '尚未准备固件：可以运行 inspect；备份和升级前运行 ./prepare-firmware.command。'
fi
echo '准备完成。运行 ./qdc507 inspect 检查模块。'
