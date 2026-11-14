# H1Music16点阵字库

来自GNU Unifont 16.0.04，使用既有 `h1-bilibili/fonts/unifont-16.0.04.hex.gz`，SHA256见 `../assets/font.json`。Roman Czyborra、Paul Hardy及Unifont贡献者；SIL OFL-1.1。像素形状未修改，生成器只选取/打包字形。22369字形，完整GB2312、JIS X0208，以及日文假名/半角/扩展；含全部11172个现代韩文预组音节、韩文字母和扩展字母。额外保留常用间隔点U+00B7。

重新生成：`python tools/generate_h1_bili_font.py --japanese --korean --output h1-qqmusic/font.h --metadata h1-qqmusic/assets/font.json`。应用仍通过原生中文输入框输入；本次扩充显示字体，不含日语或韩语输入法。
