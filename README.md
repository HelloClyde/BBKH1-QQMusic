# BBK H1 · QQ音乐

步步高 **H1/Y100 V1.41** 的非官方原生 QQ音乐客户端，480×272触屏界面。
H1管理界面、账号、歌词和M4A解复用，ESP32-S3提供通用Wi-Fi、HTTP和AAC解码。
日常使用不需要电脑或NAS常驻。应用采用GPL-3.0，第三方组件分别保留许可。

## 仓库结构

```text
src/                 QQ音乐应用（首页、列表、账号、队列和播放器）
  platform/          本应用使用的PCM、图片解码、AAC客户端、堆与libc边界
  net/               USB传输调度，底层实现引用sdk
  ui/                绘图形状和原生输入映射
  runtime/           BDA入口、初始化与链接布局
assets/              当前图标母版、字库源及许可
sdk/                 固定版本的H1 SDK子模块
third_party/         所需第三方库的源码和原始许可
tests/               音乐测试；support为纯MIPS固件/HTTP/AAC边界模型
tools/               构建、字库/图标生成、打包与仓库范围检查
docs/                截图、验证边界和来源记录
```

仓库只包含音乐程序及其依赖，不包含新闻、Bilibili、浏览器、Wi-Fi设置或H1Debug应用。
USB驱动、固件适配和H1NET协议直接使用SDK内的通用组件；没有复制另一个应用目录来满足include。
图片模块只解码JPEG/PNG，AAC模块直接调用本应用回调；测试也不导入其他应用的框架或硬件调试CLI。

## 快速开始

在[Releases](https://github.com/HelloClyde/BBKH1-QQMusic/releases)下载预览版BDA或安装ZIP。
将 **`H1QQMusic.bda`** 复制到 **`A:\应用\程序\H1QQMusic.bda`**，保持原有账号/配置文件。

1. ESP USB1通过带数据的软线OTG连接H1 Mini-USB数据线，USB2独立供电。ESP是USB主机，H1是设备。
2. 使用ESP32-S3通用固件 **0.4.4**，先通过“H1 Wi-Fi设置”保存2.4GHz网络，再打开QQ音乐。
3. 支持已插线启动，合作停止兼容H1Debug后软件重新枚举；联网应用依次独占USB。
4. 启动时若系统询问是否连接USB，选择否/取消，让应用接管连接。

| 功能 | 按键/触屏 |
| --- | --- |
| 浏览/搜索 | H热歌榜，S原生中文/拼音搜索，上下选择、左右翻页；列表上下拖动 |
| 播放/暂停 | Enter点播，播放页空格/Enter/P暂停或恢复；触摸按钮 |
| 音量/定位 | 上下调音量，左右跳转10秒；点击进度条 |
| 上下首 | N上一首、M下一首，使用点播时捕获的本页队列（最多12首） |
| 模式 | B或右上角按钮：顺序、列表循环、单曲循环、随机；真实EOF自动切歌 |
| 后台播放 | Esc返回列表，侧栏“正在播放”回到同一首；再按Esc退出并停止 |
| 登录 | A账号，Q QQ扫码、W微信扫码、R刷新、L退出登录 |

顺序模式到本页末尾停止，单曲循环允许手动换歌，随机避免连续重复且保留上一首历史。
自动切歌跳过明确无权限歌曲，网络错误停止并提示；扫码/登录不绕过上游播放权限。
账号与授权逻辑在H1，凭据为`A:\QQMusic.auth0/1`，ESP不保存QQ音乐账号；勿公开分享凭据。
模式在正常退出时保存到`A:\QQMusic.cfg`。歌曲、封面、歌词在运行时请求，不打包进仓库。

### 开发构建

已验证Windows x64、Python3.12、GNU MIPS15.2.0；工具链下载含固定SHA-256校验。

```powershell
git clone --recurse-submodules https://github.com/HelloClyde/BBKH1-QQMusic.git
cd BBKH1-QQMusic
git submodule update --init
python -m pip install -r requirements-build.txt
python tools/install_gnu_toolchain.py
$env:H1_GNU_BIN = (Resolve-Path .tools/toolchain/bin).Path
python tools/check_repository.py
python tools/build_h1_qqmusic.py --all
python tools/package_release.py
```

正式版`dist/H1QQMusic.bda`；`H1QQMusicDbg.bda`仅用于MIPS邮箱模型测试，不是H1Debug应用。
`dist/release/`包含正式BDA、带“应用/程序”目录的安装ZIP、构建信息和SHA256SUMS。
可设置`H1_GNU_BIN`复用相同版本工具链。构建使用相对路径、固定时间、稳定归档顺序；
图标母版、字库HEX及生成器齐全，不依赖系统商业字体或在线图片服务。

```powershell
python -m pip install -r requirements-test.txt
python tests/test_modes.py
python tests/test_buffer.py
python tests/test_navigation.py
```

另外`python tests/test_stream.py`验证真实C协议/分段预取，需`HOST_CC`或PATH中的gcc。
测试为实际链接MIPS程序和真实合成AAC，明确模拟固件/输入/DAC/HTTP边界，不打开串口。

## 截图

![H1首页](docs/screenshots/hardware-home.png)

物理H1的旧0.1.11安装观察截图，在USB交接前采集；不作为0.1.12的实体联网/试听证明。

![模型播放页](docs/screenshots/model-player.png)
![模型列表](docs/screenshots/model-list.png)

模型截图运行实际链接MIPS程序，仅使用合成歌曲/封面和测试账户，无真实音乐或用户凭据。

## 依赖

成品：H1/Y100 **V1.41**、带PSRAM的ESP32-S3、通用固件0.4.4、数据OTG和独立电源。
SDK子模块固定 **`63fa3c825feae5d9a1fa04572458fd5a5dbe847b`**，
来自[HelloClyde/bbk-h1-bda-sdk](https://github.com/HelloClyde/bbk-h1-bda-sdk)。
本次明确改为复用已公开的SDK通用USB/协议组件，避免复制其他应用的驱动目录。
板卡选型、J-OTG/供电/Type-C CC、固件与Wi-Fi样例见[SDK文档](https://github.com/HelloClyde/bbk-h1-bda-sdk/blob/63fa3c825feae5d9a1fa04572458fd5a5dbe847b/docs/esp32.md)。

其余为FFmpeg0.6.7（MOV解复用）、musl1.2.5、TLSF3.1、cJSON、libpng1.6.43、
zlib1.3.1、IJG JPEG9f、GNU Unifont16.0.04。源码、许可和来源见[THIRD_PARTY.md](THIRD_PARTY.md)。
Python依赖固定在requirements文件；Unicorn/PyAV只供测试，不是成品使用依赖。

## 验证与限制

见[验证边界](docs/VERIFICATION.md)。0.1.12整理仓库依赖和测试结构，未新增播放功能。
近期约90秒短停改动、自动下一首/四模式仍待最终实体试听，不以模型通过代替物理听感。
上游接口/地区/歌曲权限可能影响可用性；支持C400标准M4A/AAC，不含个人歌单/收藏写入、无损、MV或QRC逐字歌词。
QQ/微信均有扫码流程，尚未把一次手机方式反馈扩大为两种方式全部完成实体验收。

## 感谢

- HelloClyde的[Tesla Media Center](https://github.com/HelloClyde/tesla-media-center)，固定参考
  `9d7cb51cf5ddf3e02fa8d6e1c129168d11af4aae`，GPL-3.0；参考权限、队列、歌词和扫码，指纹见`docs/tmc-reference.json`。
- MrDefinition1999的H1 BDA SDK，以及H1接口研究与硬件测试参与者。
- FFmpeg、Rich Felker及musl贡献者、Matthew Conte/TLSF、Dave Gamble/cJSON、libpng、zlib、IJG、
  Roman Czyborra、Paul Hardy及Unifont贡献者。原生输入映射来源声明保留Adobe/Noto归属，未附其字形图像。

QQ音乐名称、标志及上游内容属于权利人，本项目不代表腾讯或步步高。
许可证见[LICENSE](LICENSE)和[THIRD_PARTY.md](THIRD_PARTY.md)。
