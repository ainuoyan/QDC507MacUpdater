# 固件与加载器准备

仓库只附原始 `manifest.json`，不附固件二进制。目标为 `QDC507GLEFM21_01.001.02.004`；来源和授权状态见 [SOURCES.md](../docs/SOURCES.md) 与 [NOTICE.md](../NOTICE.md)。

准备后的目录必须是：

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

## 已有匹配的文件

如已有这六份文件，将 `update/` 放到本目录下，保持路径不变。工具核对大小和 SHA-256；没有匹配的加载器不能升级。

## 从指定管理程序静态提取

也可以准备来源镜像内的 Linux amd64 `/app/dji-fw-manager`，再在 macOS 运行：

```bash
python3 tools/extract_firmware.py /路径/dji-fw-manager
```

脚本先核对管理程序的大小与固定 SHA-256，仅读取其内嵌数据，不执行程序。全部文件与仓库清单一致才写入；已有不同内容的文件会导致停止，已有相同内容的文件保持原样。新文件先写入临时文件并同步，再以不覆盖已有目标的方式创建。只有本文记录的 0.1.0 管理程序受支持，不接受未知版本或任意固件。

如果使用装有 Docker 的机器取得管理程序，可以创建但不启动容器后复制文件。以下命令不启动管理服务，不挂载 USB：

```bash
docker pull --platform linux/amd64 canghaiwuhen/dji-qdc507-firmware-manager@sha256:c087fab8bfab282b04265e6ce9e2da753819d4956ecc15e82d1ecf8ecb1b34a2
docker create --platform linux/amd64 --name qdc507-asset-copy canghaiwuhen/dji-qdc507-firmware-manager@sha256:c087fab8bfab282b04265e6ce9e2da753819d4956ecc15e82d1ecf8ecb1b34a2
docker cp qdc507-asset-copy:/app/dji-fw-manager ./dji-fw-manager
docker rm qdc507-asset-copy
python3 tools/extract_firmware.py ./dji-fw-manager
```

Docker 只是在这里获取管理程序的一种办法，macOS 刷写本身不需要 Docker。如在另一台机器取得文件，将程序传回 Mac 再静态提取即可。镜像下载需要网络，本文未保证未来仍可访问。

完成后运行 `./setup.sh` 与 `./qdc507 verify-firmware`。不要把取得的固件、加载器或管理程序加入 GitHub；本仓库没有为它们授予再分发许可，`.gitignore` 已忽略这些本地文件。
