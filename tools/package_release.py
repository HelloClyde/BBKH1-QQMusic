"""Package only the exact built native BDA, notices and a deterministic install ZIP."""
from pathlib import Path
import hashlib,json,os,re,shutil,sys,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'sdk'))
from h1_bda.validate import validate_bda
def main():
    version=(ROOT/'VERSION').read_text(encoding='utf-8').strip();assert re.fullmatch(r'\d+\.\d+\.\d+',version)
    tag=os.environ.get('GITHUB_REF','')
    if tag.startswith('refs/tags/') and tag!='refs/tags/v'+version:raise RuntimeError('Tag/VERSION mismatch')
    source=ROOT/'dist/H1QQMusic.bda';meta=json.loads(source.with_suffix('.build.json').read_text(encoding='utf-8'))
    assert meta['version']==version and meta['sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
    assert validate_bda(source)['ok'] and meta['sdk_commit']=='259c11f31fb31343b8a08e046037d89934ee1132'
    out=ROOT/'dist/release';out.mkdir(exist_ok=True)
    shutil.copy2(source,out/source.name)
    (out/'H1QQMusic.build.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    notices=[('LICENSE','licenses/QQMusic-GPL-3.0.txt'),('THIRD_PARTY.md','THIRD_PARTY.md'),
        ('sdk/LICENSE','licenses/H1-SDK-Apache-2.0.txt'),('sdk/NOTICE','licenses/H1-SDK-NOTICE.txt'),
        ('sdk/sdk/media/third_party/ffmpeg-0.6.7/COPYING.LGPLv2.1','licenses/FFmpeg-LGPL-2.1.txt'),
        ('sdk/sdk/media/third_party/ffmpeg-0.6.7/LICENSE','licenses/FFmpeg-LICENSE.txt'),
        ('sdk/sdk/media/third_party/musl-1.2.5/COPYRIGHT','licenses/musl-COPYRIGHT.txt'),
        ('sdk/sdk/media/third_party/tlsf/tlsf.h','licenses/TLSF-notice.txt'),
        ('sdk/sdk/media/third_party/libpng-1.6.43/LICENSE','licenses/libpng-LICENSE.txt'),
        ('sdk/sdk/media/third_party/zlib-1.3.1/LICENSE','licenses/zlib-LICENSE.txt'),
        ('sdk/sdk/media/third_party/jpeg-9f/README','licenses/IJG-README.txt'),
        ('third_party/cjson/LICENSE','licenses/cJSON-MIT.txt'),
        ('sdk/sdk/media/fonts/OFL-1.1.txt','licenses/Unifont-OFL.txt'),
        ('sdk/sdk/media/fonts/LICENSE-upstream.txt','licenses/Unifont-upstream.txt'),
        ('sdk/sdk/media/fonts/Noto-OFL.txt','licenses/Noto-OFL.txt')]
    instruction=('QQ音乐 '+version+' 预览版\n将“应用/程序/H1QQMusic.bda”复制到H1 A盘对应目录。\n'
        '仅H1/Y100 V1.41；ESP32-S3通用固件0.4.4。先用Wi-Fi设置完成配网。\n'
        '账号和模式配置在A:\\飞天音乐，旧文件校验后自动迁移。按B/播放页右上切换模式。\n'
        '源码与完整许可：https://github.com/HelloClyde/BBKH1-QQMusic/tree/v'+version+'\n'
        '本预览版的90秒短停修复、自动切歌/模式仍待最终实体试听。详见仓库验证记录。\n')
    entries={'应用/程序/H1QQMusic.bda':source.read_bytes(),'安装说明.txt':instruction.encode('utf-8')}
    entries.update({dest:(ROOT/src).read_bytes() for src,dest in notices})
    with zipfile.ZipFile(out/f'BBKH1-QQMusic-{version}-preview.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(entries.items()):
            i=zipfile.ZipInfo(name,(2026,11,14,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED;i.external_attr=0o100644<<16;z.writestr(i,data)
    assets=[out/'H1QQMusic.bda',out/'H1QQMusic.build.json',out/f'BBKH1-QQMusic-{version}-preview.zip']
    (out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in assets),encoding='ascii')
    print('Packaged',version,meta['sha256'],'native BDA, install ZIP, build metadata and checksums')
if __name__=='__main__':main()
