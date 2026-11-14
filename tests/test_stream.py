"""Real application network.c plus framed RPC, virtual 700ms CDN and 96kbit/s reader."""
from pathlib import Path
import argparse,hashlib,json,subprocess,os,shutil
ROOT=Path(__file__).resolve().parents[1]
def main():
    out=ROOT/'build/qqmusic/stream';out.mkdir(parents=True,exist_ok=True)
    cc=os.environ.get('HOST_CC') or shutil.which('gcc') or shutil.which('cc');assert cc,'Set HOST_CC to a host C compiler';exe=out/('stream.exe' if os.name=='nt' else 'stream')
    sources=[ROOT/x for x in ('tests/stream.c','src/network.c','sdk/sdk/esp32/common/h1net_wire.c','sdk/sdk/esp32/common/h1net_client.c','sdk/sdk/esp32/common/h1net_server.c')]
    command=[str(cc),'-std=c99','-O2','-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-int-to-pointer-cast','-Wno-pointer-to-int-cast','-Wl,--gc-sections']
    for path in ('src','sdk/sdk/esp32/common','sdk/sdk/media/target','sdk/sdk/include'):command+=['-I',str(ROOT/path)]
    r=subprocess.run([*command,*map(str,sources),'-o',str(exe)],capture_output=True,text=True)
    (out/'build.log').write_text(r.stdout+r.stderr,encoding='utf-8');r.check_returncode()
    r=subprocess.run([str(exe),'1'],capture_output=True,text=True,timeout=30)
    (out/'run.log').write_text(r.stdout+r.stderr,encoding='utf-8');r.check_returncode()
    result=json.loads(r.stdout);result.update(physical_h1=False,physical_esp32=False,method=__doc__,source_sha256={x.relative_to(ROOT).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in [Path(__file__),*sources]})
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k not in ('source_sha256','method')}))
if __name__=='__main__':main()
