"""Actual linked MIPS QQ client + MOV demux + generic HTTP/AAC + native PCM ring.
H1 firmware mixer cursor and input are scripted boundaries, not hardware timing.
Default provider fixtures contain only our synthetic music; --live uses QQ directly.
"""
from pathlib import Path
import argparse,hashlib,http.server,io,json,math,struct,sys,threading,time,urllib.parse
from fractions import Fraction
from PIL import Image
from unicorn import UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_PC,UC_MIPS_REG_RA,UC_MIPS_REG_V0
from test_h1_wifi_settings_model import Model as FirmwareModel
from h1_wifi_debug import DebugBridge
import h1_wifi_pc as pc
from h1_audio_pc import AsyncAudioService,_av as av
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/h1-qqmusic/model'
NAMES=('magic','schema','view','busy','count','selected','usb','requests','received','http','network_error','playing','ms','duration','pcm_bytes','packets','eof','play_error','volume','lyric_count','presents','inputs','panic','closing')
TRACK=struct.Struct('<15s15s15s160s128s3xII')

class Model(FirmwareModel):
    def __init__(self):
        self.hw_running=False;self.hw_samples=0;self.native_pcm=bytearray();self.next_query='钢琴';self.accept_input=True
        super().__init__(ROOT/'build/h1-qqmusic/H1QQMusicDbg.elf')
        self.completed_inputs=0
        def main_loop(u,address,size,data):
            # Capture a real return to foreground polling after key_action completes.
            if self.symbols['h1_app_main']<=u.reg_read(UC_MIPS_REG_RA)<self.main_end:
                self.completed_inputs=self.word('inputs')
        self.main_end=min(a for a in self.symbols.values() if a>self.symbols['h1_app_main'])
        poll=self.symbols['h1net_transport_poll']
        self.u.hook_add(UC_HOOK_CODE,main_loop,begin=poll,end=poll)
        table=0x80040000;self.put(0x83c0000c,struct.pack('<I',table));self.queue=0x810f0000;self.node=0x810f0100
        self.put(0x810f0200,struct.pack('<I',57))
        for i,(offset,kind) in enumerate(((0x50,'pcm-init'),(0x54,'pcm-destroy'),(0x58,'pcm-open'),(0x5c,'pcm-submit'),(0x60,'pcm-start'),(0x64,'pcm-stop'),(0x68,'pcm-close'))):
            address=0x80e30000+i*256;self.install(table,offset,address,kind)
            if kind=='pcm-submit':self.put(address+0x70,struct.pack('<3I',0x3c06810f,0x24c60000,0x00c43021))
        setter=0x80e31000;getter=0x80e31100;self.put(table+0x40,struct.pack('<2I',setter,getter))
        self.put(setter,struct.pack('<7I',0x28850065,0x24030064,0x0065200a,0x3c08810f,0xad040200,0x03e00008,0))
        self.put(getter,struct.pack('<3I',0x3c02810f,0x03e00008,0x8c420200))
        f=self.symbols['qm_native_input_raw'];self.u.hook_add(UC_HOOK_CODE,self.hook('native-input'),begin=f,end=f)
    def hook(self,kind):
        if not kind.startswith('pcm-') and kind not in ('raw-time','native-input'):return super().hook(kind)
        def run(u,address,size,data):
            a=u.reg_read(UC_MIPS_REG_A0);b=u.reg_read(UC_MIPS_REG_A1);value=1
            if kind=='raw-time':value=self.hw_samples//400
            elif kind=='native-input':
                assert not self.drawing
                if self.accept_input:
                    raw=self.next_query.encode();assert len(raw)<b;self.put(a,raw+b'\0')
                value=int(self.accept_input)
            elif kind=='pcm-open':assert struct.unpack('<2I',self.get(a,8))==(32000,1)
            elif kind=='pcm-submit':
                if not b:self.put(self.queue,bytes(4))
                else:
                    pointer,length=struct.unpack('<2I',self.get(b,8));assert length==16384
                    self.put(self.node,struct.pack('<6I',0,b,pointer,pointer+length,0,0));self.put(self.queue,struct.pack('<I',self.node))
            elif kind=='pcm-start':self.hw_running=True
            elif kind in ('pcm-stop','pcm-close'):self.hw_running=False
            u.reg_write(UC_MIPS_REG_V0,value);u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
        return run
    def consume(self):
        # Legitimate input to the modeled mixer: retire bounded valid samples.
        # Move again only after the real ring has observed the previous cursor.
        if not self.hw_running or struct.unpack('<I',self.get(self.queue,4))[0]!=self.node:return
        _,descriptor,cursor,end,_,_=struct.unpack('<6I',self.get(self.node,24));base=struct.unpack('<I',self.get(descriptor,4))[0]
        pos=(cursor-base)//2
        if self.word('read_position')!=pos:return
        n=min(640,self.word('queued'))
        for i in range(n):self.native_pcm.extend(self.get(base+2*((pos+i)%8192),2))
        self.put(self.node+8,struct.pack('<I',base+2*((pos+n)%8192)));self.hw_samples+=n
    def state(self):return dict(zip(NAMES,struct.unpack('<24I',self.get(self.symbols['qm_state'],96))))
    def play(self):return dict(zip(('ready','playing','eof','error','ms','duration','packets','pcm_bytes'),struct.unpack('<8I',self.get(self.symbols['qm_play'],32))))
    def notice(self):return self.string('qm_notice',160)
    def screenshot(self,name):Image.frombytes('RGB',(480,272),self.get(self.fb,480*272*4),'raw','BGRX').save(OUT/name)

def tone(path):
    if av is None:raise RuntimeError('PyAV required for AAC fixtures')
    container=av.open(str(path),'w',format='ipod');stream=container.add_stream('aac',rate=16000);stream.layout='mono';stream.bit_rate=48000
    for start in range(0,48000,1024):
        n=min(1024,48000-start);frame=av.AudioFrame(format='s16',layout='mono',samples=n);frame.sample_rate=16000;frame.pts=start;frame.time_base=Fraction(1,16000)
        frame.planes[0].update(struct.pack('<'+'h'*n,*[round(7000*math.sin(2*math.pi*440*(start+i)/16000)) for i in range(n)]))
        for packet in stream.encode(frame):container.mux(packet)
    for packet in stream.encode(None):container.mux(packet)
    container.close()

class Fixture:
    def __init__(self):
        tone(OUT/'tone.m4a');self.media=(OUT/'tone.m4a').read_bytes();cover=Image.new('RGB',(180,180),'#16a16c');cover.paste('#2357a0',(0,0,90,90));b=io.BytesIO();cover.save(b,'JPEG');self.cover=b.getvalue()
        self.search_fail=False;self.range_fail=False;self.events=[]
        self.tracks=[dict(songmid='00000000000001',strMediaMid='00000000000001',albummid='00000000000001',songname='钢琴测试曲',singer=[{'name':'H1合成音频'}],interval=3,pay={'payplay':0,'paydownload':1}),dict(songmid='00000000000002',strMediaMid='00000000000002',albummid='00000000000001',songname='需要授权的歌曲',singer=[{'name':'权限测试'}],interval=200,pay={'payplay':1,'paydownload':0})]
        for i in range(10):self.tracks.append(dict(self.tracks[0],songmid=f'{i+3:014d}',songname='测试歌曲 %02d'%i))
        owner=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):self.body=self.rfile.read(int(self.headers.get('Content-Length',0)));self.do_GET()
            def do_GET(self):
                path=urllib.parse.urlsplit(self.path).path;owner.events.append(dict(path=path,method=self.command,range=self.headers.get('Range')));status=200;headers={};kind='application/json';raw=b''
                if path=='/search':raw=json.dumps(dict(code=99) if owner.search_fail else dict(code=0,data={'song':{'curpage':1,'totalnum':12,'list':owner.tracks}}),ensure_ascii=False).encode()
                elif path=='/rank':raw=json.dumps(dict(code=0,song_begin=0,total_song_num=12,songlist=[{'data':s} for s in owner.tracks]),ensure_ascii=False).encode()
                elif path=='/vkey':
                    body=json.loads(self.body);mid=body['req']['param']['songmid'][0];assert body['req']['param']['filename'][0].startswith('C400')
                    raw=json.dumps({'code':0,'req':{'code':0,'data':{'retcode':0,'sip':['https://fixture.qq.com/'],'midurlinfo':[{'songmid':mid,'purl':'C400tone.m4a','result':0,'pneedbuy':0}]}}}).encode()
                elif path=='/lyric':raw=json.dumps(dict(code=0,lyric='[offset:0]\n[00:00.00]清晨的旋律\n[00:01.00]听见每一个音符\n[00:02.00]音乐陪伴H1'),ensure_ascii=False).encode()
                elif path=='/cover':raw=owner.cover;kind='image/jpeg'
                elif path=='/media':
                    raw=owner.media;kind='audio/mp4';value=self.headers.get('Range')
                    if value:
                        if owner.range_fail:status=503;raw=b'error'
                        else:
                            start,end=map(int,value.removeprefix('bytes=').split('-'));assert 0<=start<=end<len(raw);headers['Content-Range']=f'bytes {start}-{end}/{len(raw)}';raw=raw[start:end+1];status=206
                else:status=404
                self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
                for k,v in headers.items():self.send_header(k,v)
                self.end_headers()
                try:self.wfile.write(raw)
                except (ConnectionResetError,BrokenPipeError):pass
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.base='http://127.0.0.1:'+str(self.server.server_port)
    def close(self):self.server.shutdown();self.server.server_close()

class Backend(pc.Backend):
    def __init__(self,fixture):super().__init__();self.fixture=fixture
    def mapped(self,url):
        u=urllib.parse.urlsplit(url)
        if u.hostname=='u.y.qq.com':p='/vkey'
        elif 'client_search_cp' in u.path:p='/search'
        elif 'toplist_cp' in u.path:p='/rank'
        elif 'lyric' in u.path:p='/lyric'
        elif u.hostname=='y.gtimg.cn':p='/cover'
        elif u.hostname=='fixture.qq.com':p='/media'
        else:raise AssertionError('Unmapped URL '+u.netloc+u.path)
        return self.fixture.base+p
    def open_request(self,url,method,headers,body,maximum,timeout):return super().open_request(self.mapped(url),method,headers,body,maximum,timeout)
    def open_range(self,url,offset,length,total,timeout,referer):return super().open_range(self.mapped(url),offset,length,total,timeout,referer)

class Audio:
    def __init__(self):self.service=AsyncAudioService();self.available=self.service.available;self.sessions=[];self.session=None
    def dispatch(self,op,p):
        error,data=self.service.dispatch(op,p)
        if not error:
            if op==13:self.session={'asc':p[16:],'frames':[],'pcm':bytearray(),'part':bytearray()};self.sessions.append(self.session)
            if op==14:
                job,seq,total,offset,pts=struct.unpack_from('<5I',p);assert offset==len(self.session['part']);self.session['part'].extend(p[20:])
                if offset+len(p)-20==total:self.session['frames'].append(bytes(self.session['part']));self.session['part'].clear()
            if op==15:self.session['pcm'].extend(data[12:])
        return error,data
    def close(self):self.service.close()

class Harness:
    def __init__(self,fixture=None):
        self.m=Model();self.bridge=None;self.fixture=fixture
        self.until(lambda:struct.unpack('<I',self.m.get(self.m.symbols['h1net_debug_mailbox']+16,4))[0]==1)
        self.bridge=DebugBridge(self.m,ROOT/'dist/H1QQMusicDbg.build.json');self.bridge.backend.close()
        self.backend=Backend(fixture) if fixture else pc.Backend();self.audio=Audio();assert self.audio.available
        self.bridge.server=pc.Server(self.backend,self.audio)
    def until(self,condition,timeout=120):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.m.step()
            if self.bridge and not self.m.allow_exit:self.bridge.service()
            self.m.consume()
            if condition():return
        raise AssertionError(dict(state=self.m.state(),play=self.m.play(),notice=self.m.notice(),pc=hex(self.m.pc)))
    def key(self,*keys):
        before=self.m.word('inputs');self.m.keys.extend(keys);self.until(lambda:self.m.completed_inputs>=before+len(keys))
    def close(self):
        self.m.allow_exit=True;self.m.keys.extend([24,24]);self.until(lambda:self.m.pc==self.m.stop)
        assert not self.m.drawing and not self.m.allocations and not self.m.invalid
        assert all(c['mode']=='rb' and c['path'] in ('A:\\QQMusic.auth0','A:\\QQMusic.auth1','A:\\QQMusic.cfg') for c in self.m.file_calls)
        assert struct.unpack('<I',self.m.get(0x810f0200,4))[0]==57
        self.backend.close();self.audio.close()

def parser_checks(m,checks):
    src,dst,error=0x81050000,0x81060000,0x81068000
    real=(ROOT/'build/h1-qqmusic/probe/search-utf8.txt').read_bytes();m.put(src,real)
    assert m.call('qm_parse_list',src,len(real),dst,error)==0;count,page,total=struct.unpack('<3I',m.get(dst+12*TRACK.size,12));assert count==5 and total>=5
    title=TRACK.unpack(m.get(dst,TRACK.size))[3].split(b'\0')[0].decode();assert title
    for raw in (b'{',b'{"code":1}',b'{"code":0,"data":{"song":{"list":{}}}}'):
        m.put(src,raw);assert m.call('qm_parse_list',src,len(raw),dst,error)!=0
    checks.append('real MIPS parser accepts saved live QQ metadata, rejects malformed/API failures')
    m.put(src,'钢琴'.encode()+b'\0');assert m.call('qm_search_url',src,1,1,dst)==0;assert b'%E9%92%A2%E7%90%B4' in m.get(dst,401)
    m.put(src,b'x'*49+b'\0');assert m.call('qm_search_url',src,1,1,dst)!=0
    lyrics='[offset:-100]\n[00:00.20][00:01.20]测试一\n[00:02.000]测试二';raw=json.dumps(dict(code=0,lyric=lyrics),ensure_ascii=False).encode();m.put(src,raw)
    assert m.call('qm_parse_lyrics',src,len(raw),dst)==0;assert struct.unpack('<I',m.get(dst+160*116,4))[0]==3
    assert struct.unpack('<I',m.get(dst,4))[0]==100;assert m.call('qm_lyric_at',dst,0)==0xffffffff;assert m.call('qm_lyric_at',dst,1100)==1
    checks.append('UTF-8 search percent encoding and limit; TMC-style LRC offset, multiple timestamps, before-first-line semantics')

def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--output',type=Path);args=parser.parse_args()
    OUT=args.output or ROOT/('build/h1-qqmusic/live-model' if args.live else 'build/h1-qqmusic/model');OUT.mkdir(parents=True,exist_ok=True)
    class Checks(list):
        def append(self,value):super().append(value);print('PASS',value,flush=True)
    checks=Checks();report=dict(passed=False,physical_h1=False,physical_esp32=False,live_qq=args.live,method='real linked MIPS UI/JSON/HTTP/MOV/AAC client/native PCM ring; scripted firmware boundaries; real PC AAC worker',checks=checks);h=None;fixture=None
    try:
        if not args.live:fixture=Fixture()
        h=Harness(fixture);m=h.m
        if not args.live:parser_checks(m,checks)
        h.key(13);assert m.state()['count']>0;m.screenshot('01-browse.png');checks.append('browse official QQ chart through generic HTTP client (provider fixture in offline mode)')
        if args.live:
            m.next_query='纯音乐';h.key(9);assert m.state()['count']>0
            songs=[TRACK.unpack(m.get(m.symbols['qm_songs']+i*TRACK.size,TRACK.size)) for i in range(m.state()['count'])]
            ordinary=next(i for i,s in enumerate(songs) if s[-1]!=1)
            h.key(*([27]*ordinary));h.key(25);h.until(lambda:m.play()['pcm_bytes']>=32000,timeout=100);assert m.play()['ready'] and not m.play()['error'];m.screenshot('02-playing.png')
            checks.append('live QQ anonymous permitted C400 address, HTTPS CDN ranges, M4A demux and AAC PCM delivered to real MIPS ring')
        else:
            h.key(27,25);assert not m.play()['ready'] and '授权' in m.notice();h.key(37)
            checks.append('paid playback blocked without requesting a privileged URL; download cost does not block ordinary playback')
            h.key(9);assert m.state()['count']==12 and m.string('query',64)=='钢琴';m.screenshot('02-search.png')
            checks.append('native Chinese input boundary releases drawing context, restores timer and search session')
            h.key(25);h.until(lambda:m.play()['ready'] and m.play()['pcm_bytes']>=16000);m.screenshot('03-playing.png')
            checks.append('cover JPEG, LRC, original M4A range cache and asynchronous AAC worker feed actual H1 PCM ring')
            h.key(23);paused=m.play()['ms'];assert not m.play()['playing'];m.screenshot('04-paused.png')
            for _ in range(25):h.until(lambda:True)
            assert m.play()['ms']==paused;h.key(23);h.until(lambda:m.play()['playing']);h.key(35);assert not m.play()['error']
            checks.append('pause freezes progress; resume resets queued AAC at media position; seek uses MOV sample index')
            h.key(37);assert m.word('volume')==40
            h.until(lambda:m.play()['eof'] or m.play()['error']);assert m.play()['eof'] and not m.play()['error'];checks.append('complete PCM/native-ring drain reaches EOF; volume controls execute')
            h.key(24)
            session_count=len(h.audio.sessions)
            h.key(25)
            h.until(lambda:len(h.audio.sessions)>session_count and m.play()['ready'])
            session=h.audio.sessions[session_count]
            h.until(lambda:m.play()['eof'] or m.play()['error']);assert not m.play()['error']
            expected=[bytes(p) for p in av.open(str(OUT/'tone.m4a')).demux(audio=0) if p.size]
            assert session['frames']==expected,(len(session['frames']),len(expected))
            assert len(session['pcm'])>160000 and any(session['pcm']) and len(m.native_pcm)>80000 and any(m.native_pcm)
            report['linear_aac_packets']=len(expected);report['linear_pcm_bytes']=len(session['pcm']);report['native_consumed_bytes']=len(m.native_pcm)
            checks.append('linear playback AAC access units exactly match independent PyAV demux; nonzero decoded PCM is retired by actual ring')
            h.key(24);fixture.search_fail=True;h.key(9);assert m.state()['count']==12 and '接口' in m.notice();fixture.search_fail=False
            checks.append('failed search preserves previous list and reports upstream error')
            h.key(25);h.until(lambda:m.play()['playing']);h.bridge.write_word(10,0);h.until(lambda:m.play()['error'],timeout=30);assert not m.play()['eof']
            checks.append('USB loss during playback is an error, not successful end of song')
        report['pcm_bytes']=m.play()['pcm_bytes'];report['http_requests']=m.word('qm_state') if False else len(h.bridge.trace)
        report['heap_peak']=m.word('h1ns_heap_peak');h.close();h=None;checks.append('normal return closes AAC/HTTP/PCM and native context; restores volume; frees heap; no file writes')
        report['passed']=True
    finally:
        if h:report['failure']=dict(state=h.m.state(),play=h.m.play(),notice=h.m.notice(),pc=hex(h.m.pc),invalid=h.m.invalid);h.m.screenshot('failure.png');h.backend.close();h.audio.close()
        if fixture:fixture.close()
        files=[ROOT/'dist/H1QQMusicDbg.bda',ROOT/'build/h1-qqmusic/H1QQMusicDbg.elf',Path(__file__)]
        report['sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files};(OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS H1 QQ Music',len(checks),'groups; live QQ' if args.live else 'groups; synthetic provider','; no physical device claim')

if __name__=='__main__':main()
