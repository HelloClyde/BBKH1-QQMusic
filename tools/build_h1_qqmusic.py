"""Build independent H1 QQ Music client; generic HTTP/AAC peripheral only."""
from pathlib import Path
import argparse,hashlib,json,sys
import build_h1_netsurf as shared
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/h1-qqmusic';SDK=ROOT/'sdk'
SDK_REV='067fe072477861dfc8949d7b1a55279fb92d2548'

def build(debug):
    name='H1QQMusicDbg' if debug else 'H1QQMusic';group='qqmusic-debug' if debug else 'qqmusic-native'
    sources=[ROOT/p for p in ('h1-qqmusic/main.c','h1-qqmusic/core.c','h1-qqmusic/queue.c','h1-qqmusic/network.c','h1-qqmusic/account.c','h1-qqmusic/vendor/cjson/cJSON.c','h1-qqmusic/player.c','h1-qqmusic/audio_remote.c',
        'h1-news/image.c','h1-netsurf/target/libc.c','h1-netsurf/target/heap.c','h1-netsurf/vendor/tlsf/tlsf.c','h1-netsurf/target/audio.c',
        'h1-debug/firmware.c','h1-debug/usb.c','h1-wifi/h1/transport.c','h1-wifi/common/h1net_wire.c','h1-wifi/common/h1net_client.c','src/runtime/startup.c','src/runtime/entry.S')]
    inputs=sources+sorted((ROOT/'h1-qqmusic').glob('*.h'))+[Path(__file__),ROOT/'tools/prepare_h1_music_assets.py',ROOT/'h1-qqmusic/assets/icon.png',ROOT/'h1-qqmusic/assets/icon-h1-centered-v4.png',ROOT/'h1-qqmusic/assets/icon-h1-centered-design.json',ROOT/'h1-bilibili/font.h']
    identity=hashlib.sha256(b''.join(p.read_bytes() for p in inputs)).hexdigest();build_id=int(identity[:8],16)
    flags=['-I'+str(ROOT/'h1-qqmusic'),'-I'+str(ROOT/'h1-netsurf/target'),'-I'+str(ROOT/'h1-netsurf/vendor/ffmpeg-0.6.7'),'-DCJSON_NESTING_LIMIT=32','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-misleading-indentation']
    if debug:flags+=['-DH1NET_DEBUG_TRANSPORT=1',f'-DH1NET_DBG_BUILD_ID=0x{build_id:08x}u']
    archive=shared.compile_group(group,sources,flags,source_options={'libc.c':['-Wno-unused-parameter'],'player.c':['-std=gnu99','-Wno-error=incompatible-pointer-types']})
    libs=[shared.BUILD/(s+'.a') for s in ('libc','jpeg','png','zlib',*shared.FFLIBS)]
    OUT.mkdir(parents=True,exist_ok=True);(ROOT/'dist').mkdir(exist_ok=True);elf=OUT/(name+'.elf');raw=OUT/(name+'.bin');rsp=OUT/(name+'-link.rsp')
    args=[*shared.FLAGS,'-nostdlib','-Wl,--gc-sections','-Wl,--build-id=none','-Wl,-T,'+str(ROOT/'src/runtime/h1.ld'),'-Wl,-Map,'+str(OUT/(name+'.map')),'-o',elf,'-Wl,--start-group',archive,*libs,'-lgcc','-Wl,--end-group']
    rsp.write_text('\n'.join('"'+str(v).replace('\\','/')+'"' for v in args));shared.run([shared.CC,'@'+str(rsp)]);shared.run([shared.TC/('mipsel-none-elf-objcopy.exe' if sys.platform=='win32' else 'mipsel-none-elf-objcopy'),'-O','binary',elf,raw])
    sys.path.insert(0,str(SDK));from h1_bda.header import HeaderFields,encode_header
    from h1_bda.resources import PAYLOAD_OFFSET,RESOURCE_OFFSET,RESOURCE_SIZES,build_icon_resources
    from h1_bda.validate import validate_bda
    from elftools.elf.elffile import ELFFile
    payload=raw.read_bytes();size=(PAYLOAD_OFFSET+len(payload)+3)&~3;fields=HeaderFields(category=0x47,file_size_minus_4=size-4,payload_offset=PAYLOAD_OFFSET,resource_offset=RESOURCE_OFFSET,resource_sizes=RESOURCE_SIZES)
    data=encode_header(fields,title='QQ音乐调试' if debug else 'QQ音乐',build_time='2026-11-14 00:00:00')+build_icon_resources(ROOT/'h1-qqmusic/assets/icon.png')+payload;data+=bytes(size-len(data))
    artifact=ROOT/'dist'/(name+'.bda');artifact.write_bytes(data);validation=validate_bda(artifact)
    if not validation['ok']:raise RuntimeError(validation)
    with elf.open('rb') as f:symbols={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols()}
    fingerprints={}
    for p in inputs+[ROOT/'src/runtime/h1.ld']:fingerprints[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for stamp in (shared.BUILD/group).glob('*.json'):
        for p,h in json.loads(stamp.read_text())['inputs'].items():fingerprints[Path(p).relative_to(ROOT).as_posix()]=h
    report=dict(version='0.1.11',artifact=artifact.relative_to(ROOT).as_posix(),elf=elf.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest(),elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),size=size,validation=validation,source_sha256=fingerprints,
        sdk_commit=SDK_REV,firmware_required='HTTP_REQUEST and AAC features (0.3.0+)',hardware_verified=False,transport='h1debug-mailbox' if debug else 'native-usb',state_address=symbols['qm_state'],state_words=24)
    if debug:report['debug_mailbox']=dict(address=symbols['h1net_debug_mailbox'],size=1660,magic=0x31445748,build_id=build_id,tx_offset=604,rx_offset=1132,url_offset=200,url_length_offset=196,connection_tokens=True)
    artifact.with_suffix('.build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('PASS',name,size,'bytes; structural BDA validation only')

def main():
    p=argparse.ArgumentParser();p.add_argument('--all',action='store_true');p.add_argument('--debug-transport',action='store_true');a=p.parse_args()
    if shared.run(['git','-c',f'safe.directory={SDK.as_posix()}','-C',SDK,'rev-parse','HEAD']).strip()!=SDK_REV:raise RuntimeError('SDK revision mismatch')
    from prepare_h1_music_assets import prepare
    prepare();shared.headers();shared.libc();shared.images();shared.build_ffmpeg(ROOT,shared.compile_group)
    for debug in (True,False) if a.all else (a.debug_transport,):build(debug)

if __name__=='__main__':main()
