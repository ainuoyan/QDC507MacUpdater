# 一键准备固件

在项目根目录运行：

```bash
./prepare-firmware.command
```

也可以在 Finder 中双击 `prepare-firmware.command`。需要 Python 3.9 或更新版本；不需要 Docker、libusb，也不需要连接模块。

工具从原作者公开镜像下载包含管理程序的固定数据层，约 **55 MiB**，再静态提取目标固件 **`QDC507GLEFM21_01.001.02.004`（V01.01.0204）**。它不会启动容器、执行原管理程序或访问 USB。镜像层、管理程序、清单及六份载荷都会核对固定大小和 SHA-256。

准备完成后：

```bash
./setup.sh
./qdc507 verify-firmware
```

固件已完整且校验通过时，再次运行会直接跳过下载。管理程序保存在 `.firmware-cache/`，缺少固件时可从已校验的缓存重新提取；固件及缓存均已加入 Git 忽略规则，不随本仓库分发。来源和版权说明见 [SOURCES.md](../docs/SOURCES.md) 与 [NOTICE.md](../NOTICE.md)。

## 遇到问题

- 下载失败或中断：检查网络后重新运行；临时下载会清理，不支持断点续传。原镜像需要可访问，本文不保证未来仍可下载。
- 缓存校验失败：删除 `.firmware-cache/dji-fw-manager` 后重新运行。
- 已有固件内容不匹配：工具会停止且不会覆盖。先保留现有文件，再将冲突文件移出 `firmware/update/` 后重试；不要修改固定哈希绕过校验。

## 已有文件或离线准备

已有匹配的六份文件时，将 `update/` 放到本目录下，保持结构：

```text
firmware/
├── manifest.json
└── update/
    ├── RAWDATA.bin
    ├── aboot.bin
    ├── boot.bin
    ├── recoveryfs.bin
    ├── system.bin
    └── firehose/
        └── prog_nand_firehose_9x07.mbn
```

也可以在其他机器取得指定镜像中的 Linux amd64 `/app/dji-fw-manager`，传回 Mac 后离线提取：

```bash
python3 tools/extract_firmware.py /路径/dji-fw-manager
```

只接受来源记录中的 0.1.0 管理程序；全部内嵌文件校验通过才写入，已有相同内容的文件保持原样，已有不同内容的文件会导致停止。无匹配的 Firehose 加载器不能备份或升级。
