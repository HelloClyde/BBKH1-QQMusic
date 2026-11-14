# 来源与许可

应用原创代码、适配/测试和构建脚本按 GPL-3.0 提供，见 LICENSE；不将该许可覆盖到第三方组件。
H1NET/USB原创部分沿用已获权利人同意的额外Apache-2.0许可，详见通用SDK；本应用整体仍为GPL-3.0。

| 组件/路径 | 来源与许可 |
| --- | --- |
| `sdk/` | MrDefinition1999/bbk-h1-bda-sdk，固定067fe072477861dfc8949d7b1a55279fb92d2548，Apache-2.0；保留sdk/LICENSE/NOTICE |
| TMC参考 | HelloClyde/tesla-media-center，9d7cb51cf5ddf3e02fa8d6e1c129168d11af4aae，GPL-3.0；参考指纹在h1-qqmusic/tmc-reference.json |
| `h1-netsurf/vendor/ffmpeg-0.6.7/` | https://ffmpeg.org/releases/ffmpeg-0.6.7.tar.bz2 ，LGPL-2.1-or-later构建配置；原LICENSE/COPYING.*及逐文件声明保留；配置在h1-netsurf/config/ffmpeg.h。未启用GPL/nonfree组件 |
| `h1-netsurf/vendor/musl-1.2.5/` | https://musl.libc.org/releases/musl-1.2.5.tar.gz ，MIT及COPYRIGHT列出的组件声明，保留完整COPYRIGHT |
| `h1-netsurf/vendor/tlsf/` | Matthew Conte，TLSF3.1，BSD-3-Clause，许可正文位于tlsf.h |
| `h1-qqmusic/vendor/cjson/` | Dave Gamble及cJSON贡献者，MIT，保留LICENSE及源文件声明 |
| `h1-netsurf/vendor/libpng-1.6.43/` | https://download.sourceforge.net/libpng/libpng-1.6.43.tar.gz ，libpng-2.0，保留LICENSE |
| `h1-netsurf/vendor/zlib-1.3.1/` | https://zlib.net/fossils/zlib-1.3.1.tar.gz ，Zlib，保留LICENSE |
| `h1-netsurf/vendor/jpeg-9f/` | https://ijg.org/files/jpegsrc.v9f.tar.gz ，Independent JPEG Group，保留README中的许可/归属声明；部分文件许可见其原文 |
| `h1-bilibili/fonts/`、音乐font.h | GNU Unifont16.0.04，Roman Czyborra、Paul Hardy及贡献者；选择SIL OFL-1.1，源HEX、哈希、上游双许可和OFL均保留。H1Music16仅选字打包，字形像素不变 |
| `h1-wifi/browser/font.h` | Noto Sans CJK SC的已有点阵映射表，Adobe及贡献者，SIL OFL-1.1见同目录OFL.txt。音乐界面使用Unifont，此表供原生输入框GBK/Unicode映射；未附Windows字体文件 |
| 图标 | 用户提供QQ音乐标志作为参考，imagegen生成H1圆角图标；母版及设计记录在h1-qqmusic/assets。名称和标志仍属权利人，不声称商标权 |
| `tools/install_gnu_toolchain.py` | 从HelloClyde/bbk-h1-bda-sdk提交63fa3c825feae5d9a1fa04572458fd5a5dbe847b导入，Apache-2.0；工具链独立遵守GNU各组件许可，不放入源码仓库/安装包 |

`h1-netsurf/target/` 只包含格式化/堆/PCM适配，不链接NetSurf浏览器。
`h1-bilibili/` 只复用通用AAC客户端、绘图和字体，不分发Bilibili应用。
`h1-news/image.*` 只复用有界静态图片解码器，不分发新闻应用。
源码保留原相对路径以减少已验证代码的搬移；没有固件/NAND、商业ROM、真实歌曲、个人凭据或转储。

PyAV/FFmpeg测试依赖由开发者的Python环境安装，遵循其原许可；不进入H1正式BDA。
发布包附带本文件、应用LICENSE和链接组件许可摘录。修改后的LGPL组件和完整可重建应用源码随仓库/tag提供；
可用自己的兼容组件重新链接，禁止把旧构建目录或机器私有库当作发布依赖。
