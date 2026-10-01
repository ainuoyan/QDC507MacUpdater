# QDC507MacUpdater

在 macOS 上通过 USB 备份和升级 DJI 第一代百旺 QDC507 4G 模块。工具使用 Python、libusb 和 EDL，在 Mac 上执行刷写无需 Docker 或 Linux 虚拟机。

目标固件固定为 **`QDC507GLEFM21_01.001.02.004`（V01.01.0204）**。这是社区工具，与 DJI、百旺或 Quectel 无隶属或认证关系；不适用于其他型号或通用 EC25/EG25 固件。

## 功能

- 读取模块型号、当前固件和 USB 身份。
- 当前版本与目标版本一致时，直接跳过升级，不进入 EDL 或擦写。
- 连续读取两份完整 128 MiB NAND，校验大小、哈希和兼容性基线。
- 只擦写 `RAWDATA`、`aboot`、`boot`、`recoveryfs`、`system` 五个固定范围。
- 逐分区回读，再进行全盘回读：目标区必须匹配固件，非目标区必须与原备份一致。
- 复位后检查固件版本、设备身份及原 USB 配置。

工具比较的是当前版本与内置目标版本是否相同，不会联网查询官方最新版本，也不进行版本高低排序。

## 环境要求

- macOS、Python 3.9 或更新版本。
- Homebrew libusb；支持 `/opt/homebrew/lib/` 与 `/usr/local/lib/` 库路径。
- 一颗 QDC507 模块、可靠的 USB 数据连接与供电。
- 每次任务至少 640 MiB 空闲磁盘空间。
- 备份或升级需要与清单完全匹配的固件和 Firehose 加载器。

普通模式支持 `2c7c:0125`、`2ca3:4006`，下载模式为 `05c6:9008`。VID/PID 相同不代表型号兼容，工具还会检查 AT 型号、固件系列及 NAND 基线。同一时间只连接一颗目标模块。

## 安装与检查

```bash
brew install libusb
./setup.sh
./qdc507 inspect
```

`setup.sh` 在项目目录创建 `.venv/` 并安装依赖。`inspect` 不需要固件文件。

备份或升级前，在项目根目录运行以下命令，或在 Finder 中双击 `prepare-firmware.command`：

```bash
./prepare-firmware.command
./qdc507 verify-firmware
```

固件准备工具从原作者公开镜像下载约 55 MiB 数据，自动静态提取并校验，无需 Docker，也不访问 USB。已有完整固件时跳过下载。本仓库不分发第三方固件或加载器；离线准备和故障处理见 [固件准备说明](firmware/README.md)。

固件清单、文件大小或 SHA-256 不匹配时，工具会停止。不要修改固定哈希绕过检查。

## 备份与升级

```bash
./qdc507 backup
./qdc507 upgrade
```

`backup` 完成双份全盘备份后复位，检查设备仍为原固件。
`upgrade` 在刷写前执行同样的备份检查；已有目标版本时直接退出，不执行备份或刷写。
五区擦写和回读、全盘比对及复位后 AT 检查全部通过才会报告成功，不能只凭 ACK 或版本文字判断升级完整。

任务目录保存在 `sessions/`，包含设备身份、完整 NAND 和运行日志。该目录已加入 Git 忽略规则，请保留用于恢复与诊断，不要公开上传。当前 CLI 没有自动恢复或降级命令。

## 中断与 USB 重新连接

工具会打印任务目录。如果尚未开始写入，设备仍为同一颗模块且 USB 物理端口未改变，可按原任务继续：

```bash
./qdc507 backup --session /绝对路径/sessions/任务目录
./qdc507 upgrade --session /绝对路径/sessions/任务目录
```

同一任务中的身份记录、USB 端口和可用的总线编号用于核对设备，不要在任务中更换模块。

- 出现 `write-started.json` 后禁止自动重刷；保留标记、原备份和日志。
- 已有 `result.json` 的任务不能复用。
- 中断或不完整的备份文件不会被覆盖；复用完整备份前会重新读取当前 NAND 比对。
- USB 短写、异常、缺少完成 ACK 或回读不一致时立即停止，不自动重发载荷或继续下一分区。
- 读取连续 30 秒没有进展会失败；单次 EDL 子进程最多等待 10 分钟。

同一用户的工具实例共用进程锁。刷写期间避免其他 USB 管理软件占用模块。失败后查看工具打印的日志路径，保留当前连接与任务文件分析原因。

## 固件更新说明

White-Alone 原文中的 DJI 设备界面说明：V01.01.0204 支持 APN 自适应，并解决部分专网 SIM 卡适配问题。
更新界面图片、出处及解释见 [固件更新说明](docs/FIRMWARE_CHANGES.md)。这段说明未提及 MBIM 修复或网速提升，不能据此保证这些效果。

## 开发验证

```bash
.venv/bin/python -B -m unittest discover -v
```

测试覆盖固件下载与缓存校验、固件和身份校验、双份备份一致性、任务复用、NAND 擦写边界、USB 传输错误和回读验证。
测试使用临时文件与模拟 USB，不操作真实模块。未准备 `firmware/update/` 时，真实固件文件校验测试会明确跳过；准备完整文件后该项会执行。

## 来源、许可证与致谢

固件资料和备份、升级、回读流程参考 [White-Alone 的《大疆4G模组和闲鱼伪基站二三事》](https://blog.white-alone.com/posts/%E5%A4%A7%E7%96%864G%E6%A8%A1%E7%BB%84%E5%92%8C%E9%97%B2%E9%B1%BC%E4%BC%AA%E5%9F%BA%E7%AB%99%E4%BA%8C%E4%B8%89%E4%BA%8B) 及其公开镜像 `canghaiwuhen/dji-qdc507-firmware-manager:0.1.0`。升级说明图片也引用自该原文，保留作者、原文和原图链接。

EDL 源码来自 [B. Kerler / bkerler/edl](https://github.com/bkerler/edl)，保留原作者版权和 GPLv3 许可证。macOS 适配涉及四个文件，修改说明与补丁见 [NOTICE.md](NOTICE.md)。

本项目代码采用 [GNU GPLv3](LICENSE)。第三方图片、固件及加载器不因本项目引用而重新授权为 GPLv3；完整来源、固定摘要和版权边界见 [来源记录](docs/SOURCES.md)。
