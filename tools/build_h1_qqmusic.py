"""Build independent H1 QQ Music client; generic HTTP/AAC peripheral only."""
from pathlib import Path
import argparse,hashlib,json,sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/qqmusic';SDK=ROOT/'sdk'
sys.path.insert(0,str(SDK))
import os
os.environ.setdefault('H1_MEDIA_BUILD',str(ROOT/'build/deps'))
from h1_bda import media as shared
SDK_REV='259c11f31fb31343b8a08e046037d89934ee1132'

def build(debug):
    name='H1QQMusicDbg' if debug else 'H1QQMusic';group='qqmusic-debug' if debug else 'qqmusic-native'
    sources=[ROOT/p for p in ('src/main.c','src/core.c','src/queue.c','src/network.c','src/account.c',
        'src/storage.c','src/player.c','third_party/cjson/cJSON.c')]+shared.sources()
    inputs=sources+sorted((ROOT/'src').rglob('*.h'))+[Path(__file__),ROOT/'tools/prepare_h1_music_assets.py',ROOT/'assets/icon.png',ROOT/'assets/icon-h1-centered-v4.png',ROOT/'assets/icon-h1-centered-design.json']
    identity=hashlib.sha256(b''.join(p.read_bytes() for p in inputs)).hexdigest();build_id=int(identity[:8],16)
    flags=['-I'+str(ROOT/'src'),'-I'+str(shared.ROOT/'target'),'-I'+str(shared.ROOT/'third_party/ffmpeg-0.6.7'),'-DCJSON_NESTING_LIMIT=32','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-misleading-indentation']
    if debug:flags+=['-DH1NET_DEBUG_TRANSPORT=1',f'-DH1NET_DBG_BUILD_ID=0x{build_id:08x}u']
    archive=shared.compile_group(group,sources,flags,source_options={'libc.c':['-Wno-unused-parameter'],'player.c':['-std=gnu99','-Wno-error=incompatible-pointer-types']})
    libs=[shared.BUILD/(s+'.a') for s in ('libc','jpeg','png','zlib',*shared.FFLIBS)]
    OUT.mkdir(parents=True,exist_ok=True);(ROOT/'dist').mkdir(exist_ok=True);elf=OUT/(name+'.elf');raw=OUT/(name+'.bin');rsp=OUT/(name+'-link.rsp')
    args=[*shared.FLAGS,'-nostdlib','-Wl,--gc-sections','-Wl,--build-id=none','-Wl,-T,'+str(shared.ROOT/'runtime/h1.ld'),'-Wl,-Map,'+str(OUT/(name+'.map')),'-o',elf,'-Wl,--start-group',archive,*libs,'-lgcc','-Wl,--end-group']
    rsp.write_text('\n'.join('"'+str(v).replace('\\','/')+'"' for v in args));shared.run([shared.CC,'@'+str(rsp)]);shared.run([shared.TC/('mipsel-none-elf-objcopy.exe' if sys.platform=='win32' else 'mipsel-none-elf-objcopy'),'-O','binary',elf,raw])
    sys.path.insert(0,str(SDK));from h1_bda.header import HeaderFields,encode_header
    from h1_bda.resources import PAYLOAD_OFFSET,RESOURCE_OFFSET,RESOURCE_SIZES,build_icon_resources
    from h1_bda.validate import validate_bda
    from elftools.elf.elffile import ELFFile
    payload=raw.read_bytes();size=(PAYLOAD_OFFSET+len(payload)+3)&~3;fields=HeaderFields(category=0x47,file_size_minus_4=size-4,payload_offset=PAYLOAD_OFFSET,resource_offset=RESOURCE_OFFSET,resource_sizes=RESOURCE_SIZES)
    data=encode_header(fields,title='QQ音乐调试' if debug else 'QQ音乐',build_time='2026-11-14 00:00:00')+build_icon_resources(ROOT/'assets/icon.png')+payload;data+=bytes(size-len(data))
    artifact=ROOT/'dist'/(name+'.bda');artifact.write_bytes(data);validation=validate_bda(artifact)
    if not validation['ok']:raise RuntimeError(validation)
    with elf.open('rb') as f:symbols={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols()}
    fingerprints={}
    for p in inputs+[shared.ROOT/'runtime/h1.ld']:fingerprints[Path(os.path.relpath(p,ROOT)).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for stamp in (shared.BUILD/group).glob('*.json'):
        for p,h in json.loads(stamp.read_text())['inputs'].items():fingerprints[Path(os.path.relpath(p,ROOT)).as_posix()]=h
    report=dict(version='0.1.13',artifact=artifact.relative_to(ROOT).as_posix(),elf=elf.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest(),elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),size=size,validation=validation,source_sha256=fingerprints,
        sdk_commit=SDK_REV,firmware_required='HTTP_REQUEST and AAC features (0.3.0+)',hardware_verified=False,transport='h1debug-mailbox' if debug else 'native-usb',state_address=symbols['qm_state'],state_words=24)
    if debug:report['debug_mailbox']=dict(address=symbols['h1net_debug_mailbox'],size=1120,magic=0x31445748,build_id=build_id,tx_offset=64,rx_offset=592,connection_tokens=True)
    artifact.with_suffix('.build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('PASS',name,size,'bytes; structural BDA validation only')

def main():
    p=argparse.ArgumentParser();p.add_argument('--all',action='store_true');p.add_argument('--debug-transport',action='store_true');a=p.parse_args()
    if shared.run(['git','-c',f'safe.directory={SDK.as_posix()}','-C',SDK,'rev-parse','HEAD']).strip()!=SDK_REV:raise RuntimeError('SDK revision mismatch')
    from prepare_h1_music_assets import prepare
    prepare();shared.libraries()
    for debug in (True,False) if a.all else (a.debug_transport,):build(debug)

if __name__=='__main__':main()
