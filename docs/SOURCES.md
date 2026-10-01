# 来源与引用

## 固件、管理程序及配套 EDL

固件资料及备份、升级、回读流程参考 White-Alone 的 [《大疆4G模组和闲鱼伪基站二三事》](https://blog.white-alone.com/posts/%E5%A4%A7%E7%96%864G%E6%A8%A1%E7%BB%84%E5%92%8C%E9%97%B2%E9%B1%BC%E4%BC%AA%E5%9F%BA%E7%AB%99%E4%BA%8C%E4%B8%89%E4%BA%8B)（文章显示日期：2026-07-29）。直接取得来源为作者公开的第三方镜像：

- 镜像：`canghaiwuhen/dji-qdc507-firmware-manager:0.1.0`
- 公开入口：[Docker Hub](https://hub.docker.com/r/canghaiwuhen/dji-qdc507-firmware-manager)
- 镜像索引摘要：`sha256:bf0afe1b5bcd3ac01b3b4d1fb993f8b2992e6bcebd54a8584f70a74936b367db`
- Linux amd64 manifest：`sha256:c087fab8bfab282b04265e6ce9e2da753819d4956ecc15e82d1ecf8ecb1b34a2`
- 配套 EDL 所在层：`sha256:be017854d032974f07885290ffc4082d8f2955245cefe178c675e4b2af8b000b`
- 管理程序所在层：`sha256:3eb0f67192fcf4e29c41f3d1740266d35c963192e41fbecc99ac0169deab4ddf`（57,404,289 字节）
- 管理程序位置：`/app/dji-fw-manager`
- 管理程序 SHA-256：`c8b0c8192c8f35c81f665711e0331a56e173157f2a9f715024f21ce85e123465`
- 内嵌固件目录：`assets/firmware/qdc507-01.001.02.004/`
- 原清单 SHA-256：`2df3c8bc365fd7140ca06c1854e35f7deab7428abd50f85fcdaf4e0ed6b2baab`

提取工具仅读取指定管理程序的 ELF/Go 内嵌数据，不执行该程序；输出清单、五个分区及一个加载器，逐项校验大小和 SHA-256。准备方法见 [固件说明](../firmware/README.md)。

镜像不是 DJI 官方下载入口。这些摘要用于固定来源和文件内容，不代表厂商签名或认证，也不证明二进制的再分发许可。镜像标签可能变化，因此一键准备工具直接下载固定摘要的数据层，不跟随标签更新。下载通过 [Registry API](https://distribution.github.io/distribution/spec/api/) 和 [Docker Registry 认证接口](https://docs.docker.com/reference/api/registry/auth/) 完成，不需要 Docker 客户端。

## EDL 原作者与本地适配

上游项目：[B. Kerler / bkerler/edl](https://github.com/bkerler/edl)，GPLv3。
实际配套源码取自上述镜像的 `/opt/dji-tools/edl/`。镜像未记录可确认的上游 commit，以 [逐文件来源与发布哈希](evidence/edl-provenance.json) 追溯，不声称与当前 master 相同。

原作者署名、版权声明和许可证保留在 `vendor/edl/`。本项目四处文件适配的说明和完整补丁见 [NOTICE.md](../NOTICE.md)。

## 升级说明图片

- 原作者：White-Alone。
- 原文：[大疆4G模组和闲鱼伪基站二三事](https://blog.white-alone.com/posts/%E5%A4%A7%E7%96%864G%E6%A8%A1%E7%BB%84%E5%92%8C%E9%97%B2%E9%B1%BC%E4%BC%AA%E5%9F%BA%E7%AB%99%E4%BA%8C%E4%B8%89%E4%BA%8B)。
- 原图：[原文“遥控器升级固件”配图](https://raw.githubusercontent.com/white-alone/blog_img/master/%E5%A4%A7%E7%96%864G%E6%A8%A1%E7%BB%84%E5%92%8C%E9%97%B2%E9%B1%BC%E4%BC%AA%E5%9F%BA%E7%AB%99%E4%BA%8C%E4%B8%89%E4%BA%8B/1785307347818.png)。
- 引用副本：[DJI V01.01.0204 更新界面](evidence/dji-v01.01.0204-release-notes.png)。
- 来源、文字及副本哈希：[图片证据 JSON](evidence/dji-v01.01.0204-release-notes.json)。

照片显示“DJI 增强图传模块 V01.01.0204”，更新文字为“支持 APN 自适应，并解决部分专网 SIM 卡适配问题”。该图片引用自 White-Alone 原文，不是本项目拍摄。

引用副本仅去除 EXIF 附加元数据，图像内容块保持原样。图片及设备界面文字、标识的权利归原作者及相应权利人，不适用本项目代码的 GPLv3 授权。
照片不含固件发布日期、具体卡种清单或 MBIM 修复说明；文章日期不能当作固件发布日期。

## 固件系列参考

[Quectel Forums：Firmware request for EG25G-QDC507](https://forums.quectel.com/t/firmware-request-for-eg25g-qdc507/58093) 中的移远支持回复说明，`QDC507GLEFM21` 固件应向设备供应商获取。该参考用于区分 QDC507 定制固件与标准 EG25 固件，不是 V01.01.0204 的功能更新说明。

## 发布范围

仓库发布 macOS 工作流、测试、静态提取工具、配套 EDL 源码、固定清单、引用说明及图片。第三方固件、Firehose 加载器和 Go 管理程序不随仓库分发，也未被改标为 GPLv3。
