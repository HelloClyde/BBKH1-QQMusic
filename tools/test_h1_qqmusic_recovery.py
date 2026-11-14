"""Repeated real PCM-ring underruns, AAC backpressure and Korean bitmap output.
Linked MIPS app and real MOV/PyAV decoder; scripted firmware cursor/provider only.
"""
from pathlib import Path
import argparse,gzip,hashlib,http.server,json,struct,threading,time,unicodedata
from elftools.elf.elffile import ELFFile
from unicorn.mips_const import UC_MIPS_REG_V0,UC_MIPS_REG_PC,UC_MIPS_REG_RA
import test_h1_qqmusic_model as q
from test_h1_qqmusic_navigation import long_tone
import h1_wifi_pc as pc

ROOT=q.ROOT;OUT=ROOT/'build/h1-qqmusic/recovery-0.1.9';OUT.mkdir(parents=True,exist_ok=True)
class TimedModel(q.Model):
    """GUI time follows the same scripted DAC progression as the raw timer.
    One idle emulation slice advances 1ms. Host CPU slowness cannot multiply
    redraws while simulated DAC consumption is deliberately held at a cursor.
    This is a modeled firmware input, never a write to application state.
    """
    def __init__(self):self.gui_ms=0;super().__init__()
    def hook(self,kind):
        if kind!='time':return super().hook(kind)
        def run(u,address,size,data):
            u.reg_write(UC_MIPS_REG_V0,self.gui_ms);u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
        return run
    def consume(self):
        super().consume();self.gui_ms=max(self.gui_ms+1,self.hw_samples//32)
class Lyric(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        raw=json.dumps({'code':0,'lyric':'[00:00.00]사랑해요 함께 걸어요\n[00:10.00]오늘도 좋은 하루\n[00:30.00]음악을 계속 들어요'},ensure_ascii=False).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class Backend(q.Backend):
    def mapped(self,url):return self.lyric_url if '/lyric/' in url else super().mapped(url)

def underrun(m):
    assert m.hw_running and struct.unpack('<I',m.get(m.queue,4))[0]==m.node
    _,descriptor,cursor,_,_,_=struct.unpack('<6I',m.get(m.node,24));base=struct.unpack('<I',m.get(descriptor,4))[0]
    queued=m.word('queued');assert queued<7936;pos=(cursor-base)//2;consumed=queued+128
    m.put(m.node+8,struct.pack('<I',base+2*((pos+consumed)%8192)));m.hw_samples+=consumed

class Audio(q.Audio):
    busy=0;inject=None;fail_reads=False
    def dispatch(self,op,payload):
        if op==14 and self.busy:
            self.busy-=1
            if self.inject:fn=self.inject;self.inject=None;fn()
            return pc.BUSY,b''
        if op==15 and self.fail_reads:return 5,b''
        return super().dispatch(op,payload)

class Harness(q.Harness):
    def close(self):
        # Normal exit keeps the peer alive for AUDIO_CLOSE/HTTP_RELEASE.
        # The legacy helper deliberately stops serving and waits for an IO
        # timeout; a scripted GUI clock need not follow host wall time.
        self.m.allow_exit=True;self.m.keys.extend([24,24]);deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            self.m.step()
            if self.m.pc==self.m.stop:break
            if self.bridge.header()[4]==1:self.bridge.service()
            self.m.consume()
        assert self.m.pc==self.m.stop and not self.m.drawing and not self.m.allocations and not self.m.invalid
        assert not self.m.handles
        self.m.allow_exit=True;self.backend.close();self.audio.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cleanup-only',action='store_true');args=parser.parse_args()
    q.OUT=OUT;q.tone=long_tone;q.Model=TimedModel;fixture=q.Fixture();h=None;checks=[]
    fixture.tracks[0]['songname']='연애의 조건 · 한글 표시 시험';fixture.tracks[0]['singer']=[{'name':'가나다라마바사'}]
    fixture.tracks[0]['padding']={str(i):'목록 데이터' for i in range(2000)}
    lyric=http.server.ThreadingHTTPServer(('127.0.0.1',0),Lyric);threading.Thread(target=lyric.serve_forever,daemon=True).start()
    report={'passed':False,'physical_h1':False,'physical_esp32':False,'method':'linked MIPS program; real synthetic AAC/MOV/PCM; scripted cursor underruns; GUI/raw timers follow modeled DAC progress with 1ms idle slices; modeled BUSY/error replies','checks':checks}
    def passed(s):checks.append(s);print('PASS',s,flush=True)
    try:
        h=Harness(fixture);m=h.m;h.backend.close();h.audio.close()
        backend=Backend(fixture);backend.lyric_url='http://127.0.0.1:'+str(lyric.server_port)+'/lyrics';audio=Audio()
        h.backend=backend;h.audio=audio;h.bridge.server=pc.Server(backend,audio)
        h.key(13,25);h.until(lambda:m.play()['ms']>=300 and m.word('queued')<7000)
        def diag():return struct.unpack('<16I',m.get(m.symbols['qm_player_diag'],64))
        if not args.cleanup_only:
            m.screenshot('01-korean-lyrics.png')
            with (ROOT/'build/h1-qqmusic/H1QQMusicDbg.elf').open('rb') as f:
                table={s.name:(s['st_value'],s['st_size']) for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols()}
            count=table['bili_font_cp'][1]//2;codes=struct.unpack('<%uH'%count,m.get(table['bili_font_cp'][0],count*2));index={cp:i for i,cp in enumerate(codes)}
            assert count==22369 and len(index)==count and list(codes)==sorted(codes) and 0xb7 in index
            rows=m.get(table['bili_font_rows'][0],count*32);widths=m.get(table['bili_font_width'][0],count)
            upstream={int(s.split(':')[0],16):bytes.fromhex(s.split(':')[1]) for s in gzip.decompress((ROOT/'h1-bilibili/fonts/unifont-16.0.04.hex.gz').read_bytes()).decode().splitlines()}
            for cp in range(0xac00,0xd7a4):
                i=index[cp];assert widths[i]==16;expected=struct.unpack('>16H',upstream[cp]);assert struct.unpack_from('<16H',rows,i*32)==expected
            for start,end in ((0x1100,0x1200),(0x3130,0x3190),(0xa960,0xa980),(0xd7b0,0xd800)):
                assert all(cp in index for cp in range(start,end) if unicodedata.category(chr(cp))!='Cn')
            passed('all 11172 Hangul syllables match pinned Unifont pixels in linked ELF; jamo/extensions present; Korean title and lyrics render')
            audio.busy=3;audio.inject=lambda:underrun(m);before=m.play()['ms']
            h.until(lambda:diag()[12]>=1 and m.play()['ms']>before+100 or m.play()['error'],timeout=120)
            assert not m.play()['error'] and diag()[2]==0 and m.get(m.symbols['bili_audio_remote_state']+14*4,4)==bytes(4)
            passed('underrun during AAC PUSH BUSY recovers within PCM progress callback without decoder reset/deadlock')
            for n in range(1,12):
                h.until(lambda:m.word('queued')<7000 and struct.unpack('<I',m.get(m.queue,4))[0]==m.node)
                before=m.play()['ms'];underrun(m)
                h.until(lambda:diag()[12]>=n+1 and m.play()['ms']>before+80 or m.play()['error'],timeout=120)
                assert not m.play()['error'] and diag()[2]==0
            assert m.word('underruns')>=12 and diag()[12]==12
            assert struct.unpack('<I',m.get(m.symbols['bili_audio_remote_state']+14*4,4))[0]==0
            report['forced_underruns']=m.word('underruns');report['clock_recoveries']=diag()[12]
            passed('12 repeated native-ring underruns retain MOV/AAC/HTTP and continue real retired-PCM progress; AAC reset count remains zero')
            h.key(24);before=m.play()['ms'];presents=m.word('presents');h.until(lambda:m.play()['ms']>before+1000)
            assert m.play()['playing'] and m.word('presents')==presents
            h.key(35);assert m.play()['playing'] and not m.play()['error'];m.screenshot('02-background-list.png')
            passed('background list avoids progress-driven redraw; large paginated JSON yields while current audio continues')
            h.until(lambda:m.play()['eof'] or m.play()['error'],timeout=300);assert m.play()['eof'] and not m.play()['error']
            expected=[bytes(p) for p in q.av.open(str(OUT/'tone.m4a')).demux(audio=0) if p.size]
            assert audio.sessions[0]['frames']==expected
            passed('45-second stream reaches EOF; all AAC access units exactly match independent demux after repeated recovery and pagination')
            report['aac_packets']=len(expected);report['pcm_bytes']=len(audio.sessions[0]['pcm'])
        if not args.cleanup_only:h.key(25)
        h.until(lambda:m.play()['ms']>150);audio.fail_reads=True;h.until(lambda:m.play()['error'])
        assert diag()[2]==1 and diag()[3]==(0xffffffff-104)
        retained=diag();h.close();h=None;assert tuple(retained)==struct.unpack('<16I',m.get(m.symbols['qm_player_diag'],64))
        passed('a genuine remote-error response stops playback with a specific retained error snapshot; normal exit preserves diagnostics and frees resources')
        report['passed']=True
    finally:
        if h:
            report['failure']={'state':h.m.state(),'play':h.m.play(),'notice':h.m.notice(),'diag':list(struct.unpack('<16I',h.m.get(h.m.symbols['qm_player_diag'],64))),'pc':hex(h.m.pc),'http_jobs':[vars(j.info) for j in h.backend.jobs]};h.m.screenshot('failure.png');h.backend.close();h.audio.close()
        lyric.shutdown();lyric.server_close();fixture.close()
        report['sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/'build/h1-qqmusic/H1QQMusicDbg.elf',ROOT/'dist/H1QQMusicDbg.bda',ROOT/'h1-qqmusic/font.h')}
        (OUT/('cleanup-report.json' if args.cleanup_only else 'report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS',len(checks),'recovery/Korean groups; model only')
if __name__=='__main__':main()
