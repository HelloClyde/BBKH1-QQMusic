# 来源与许可

原创音乐应用、适配/测试和构建代码采用GPL-3.0；第三方组件保留各自许可，不重新套用应用许可。

| 组件 | 来源与许可 |
| --- | --- |
| `sdk/` | HelloClyde/bbk-h1-bda-sdk，63fa3c825feae5d9a1fa04572458fd5a5dbe847b，Apache-2.0。USB驱动、V1.41固件适配、H1NET直接从此子模块构建；保留sdk/LICENSE/NOTICE |
| TMC参考 | HelloClyde/tesla-media-center，9d7cb51cf5ddf3e02fa8d6e1c129168d11af4aae，GPL-3.0；指纹在docs/tmc-reference.json |
| `third_party/ffmpeg-0.6.7/` | https://ffmpeg.org/releases/ffmpeg-0.6.7.tar.bz2 ，LGPL-2.1-or-later配置；LICENSE/COPYING.*及逐文件声明保留，config/ffmpeg.h记录配置，未启用GPL/nonfree组件 |
| `third_party/musl-1.2.5/` | https://musl.libc.org/releases/musl-1.2.5.tar.gz ，MIT及COPYRIGHT所列声明 |
| `third_party/tlsf/` | Matthew Conte，TLSF3.1，BSD-3-Clause，许可全文在tlsf.h |
| `third_party/cjson/` | Dave Gamble及cJSON贡献者，MIT，保留LICENSE |
| `third_party/libpng-1.6.43/` | https://download.sourceforge.net/libpng/libpng-1.6.43.tar.gz ，libpng-2.0，保留LICENSE |
| `third_party/zlib-1.3.1/` | https://zlib.net/fossils/zlib-1.3.1.tar.gz ，Zlib，保留LICENSE |
| `third_party/jpeg-9f/` | https://ijg.org/files/jpegsrc.v9f.tar.gz ，IJG许可见README，保留逐文件原声明 |
| `assets/fonts/`、src/font.h | GNU Unifont16.0.04，Roman Czyborra、Paul Hardy及贡献者；选择SIL OFL-1.1，完整源HEX/哈希/OFL/上游双许可保留。H1Music16仅选取打包，像素形状不变 |
| `src/ui/ime_table.h` | 原生输入的Unicode/GB2312映射，提取自此前Noto映射表，保留Adobe/Noto来源和assets/fonts/Noto-OFL.txt；此处不含Noto字形像素或商业字体文件 |
| `assets/`图标 | 用户以QQ音乐标志作视觉参考，imagegen生成当前H1图标；母版和设计记录保留，商标权仍归权利人 |
| `tools/install_gnu_toolchain.py` | 来自H1 SDK63fa3c8，Apache-2.0。工具链独立遵守GNU组件许可，不进入源码/安装包 |

`src/platform/images.c`由此前有界图片解码器提取，仅JPEG/PNG解码；已删除新闻站点的URL策略。
`src/platform/aac_remote.c`由此前共享H1NET AAC客户端提取，直接使用音乐回调，不包含视频/站点/账号逻辑。
`src/ui/drawing.h`为共用像素几何；其他应用的前台、应用头文件、字形表、CLI和测试业务均未纳入。
这些原创适配的历史来源不改变版权归属；项目整体仍以GPL-3.0提供。

测试support只模拟固件边界、网络和AAC，不带硬件串口客户端。PyAV/FFmpeg测试环境遵守其原许可，
不进入正式BDA。没有BBK固件/NAND、商业ROM、真实歌曲或个人凭据。
安装ZIP附许可文本；完整源码与固定SDK可重新构建/链接，未以私有库替代可重建源码。
