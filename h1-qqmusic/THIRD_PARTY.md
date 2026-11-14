# 第三方来源

- 登录协议实现参考 [QQMusicApi的login.py](https://github.com/L-1124/QQMusicApi/blob/main/qqmusic_api/modules/login.py) 的QQ/微信Web扫码流程，以及本机TMC QQMusic应用。H1以C实现协议；不运行Python、Flask或网页前端。参考快照及下载指纹在build/h1-qqmusic/login-reference/，未包含真实账号。
- cJSON源码来自固定ESP-IDF5.5.6 checkout的components/json/cJSON，原始MIT许可保留于vendor/cjson/LICENSE。用于H1应用的账号JSON处理，不向ESP加入站点逻辑。构建将嵌套深度限制为32。
- 日文字库见fonts/README.md及OFL-1.1.txt；其余既有FFmpeg、图像库和SDK许可沿用项目原记录。
