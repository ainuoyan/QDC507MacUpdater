# 来源、版权与本地修改声明

整理日期：2026-10-01。

## 本项目代码

`qdc507.py`、启动脚本、测试、静态提取脚本及本项目编写的说明文档是本项目为 QDC507 macOS 工作流编写、整理的内容，采用仓库根目录的 GNU GPLv3 许可证。固件、加载器和第三方程序的版权不因本项目整理而转移。

## EDL 源码

上游项目：[bkerler/edl](https://github.com/bkerler/edl)。原作者 B. Kerler；原始文件的版权年份和 GPLv3 声明完整保留，许可证同时保存在 `vendor/edl/LICENSE`。

本项目使用的实际基线取自 `canghaiwuhen/dji-qdc507-firmware-manager:0.1.0` 的 `/opt/dji-tools/edl/`，不是声称直接对应 GitHub 当前 master。来源镜像未记录可确认的上游 commit，本项目不补造 commit。镜像摘要、来源层摘要及逐文件哈希见 [EDL 来源记录](docs/evidence/edl-provenance.json)。

发布目录保留运行与测试所用 Python 源码、原 README、许可证和依赖元数据；没有打包上游 Windows 驱动、预编译工具、测试二进制、下载器数据库或其他系统安装脚本。

本地修改日期为 2026-10-01，涉及：

| 文件 | 修改目的 |
| --- | --- |
| `vendor/edl/edl.py` | 为 reset 命令补齐 NAND 参数解析；被中断时返回非零退出状态 |
| `vendor/edl/edlclient/Library/Connection/usblib.py` | macOS Homebrew libusb 路径、USB 短写检测、传输异常后禁止自动重发 |
| `vendor/edl/edlclient/Library/firehose.py` | NAND 擦写结束扇区、真实擦除要求、严格 ACK 与 USB 错误处理、同步文件回读及读取无进展超时、非稀疏输入文件句柄释放 |
| `vendor/edl/edlclient/Library/firehose_client.py` | NAND 全盘读取的返回值处理 |

四个文件中另加入修改日期说明。相对镜像基线的完整差异见 [edl-local-changes.patch](docs/edl-local-changes.patch)。`PAGES_PER_BLOCK` 支持原本已存在于镜像基线，不能算作本项目新增。

## 固件、加载器及镜像

目标固件是 DJI 第一代百旺 QDC507 使用的 `QDC507GLEFM21_01.001.02.004`。直接取得来源为公开的第三方容器镜像 `canghaiwuhen/dji-qdc507-firmware-manager:0.1.0`，不是 DJI 官方下载入口。

原固件和 Firehose 加载器的权利归相应权利人；目前未确认其公开再分发许可。本仓库只提供原始清单、来源、哈希和静态提取工具，不随源码分发这些二进制，也不把它们改标为 GPL。

镜像中的 Go 管理程序没有随本仓库发布。本项目的命令行升级流程不执行该管理程序，也没有将其反编译代码作为本项目源码。

本项目与 DJI、百旺、Quectel 无隶属或认证关系；产品名仅用于识别适用设备。

## 设备界面照片

`docs/evidence/dji-v01.01.0204-release-notes.png` 引用自 White-Alone 的 [《大疆4G模组和闲鱼伪基站二三事》](https://blog.white-alone.com/posts/%E5%A4%A7%E7%96%864G%E6%A8%A1%E7%BB%84%E5%92%8C%E9%97%B2%E9%B1%BC%E4%BC%AA%E5%9F%BA%E7%AB%99%E4%BA%8C%E4%B8%89%E4%BA%8B) 中的“遥控器升级固件”配图，[原图](https://raw.githubusercontent.com/white-alone/blog_img/master/%E5%A4%A7%E7%96%864G%E6%A8%A1%E7%BB%84%E5%92%8C%E9%97%B2%E9%B1%BC%E4%BC%AA%E5%9F%BA%E7%AB%99%E4%BA%8C%E4%B8%89%E4%BA%8B/1785307347818.png)、作者和副本哈希见同目录 JSON 及 [来源记录](docs/SOURCES.md)。照片副本仅去除 EXIF 附加元数据，未修改图像内容。照片不是本项目拍摄；照片及设备界面文字、标识的权利归原作者及相应权利人，不因本项目引用而改用本项目的 GPLv3 许可证。
