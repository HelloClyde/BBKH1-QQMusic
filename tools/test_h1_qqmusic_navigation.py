"""Linked-MIPS homepage, background audio, queue and account-rights regression.
Uses synthetic media/account provider and modeled firmware inputs/cursor only.
"""
from pathlib import Path
from fractions import Fraction
import hashlib,http.server,json,math,struct,threading
import test_h1_qqmusic_model as q
import test_h1_qqmusic_accounts as a
import h1_wifi_pc as pc

ROOT=q.ROOT;OUT=ROOT/'build/h1-qqmusic/navigation-0.1.11';OUT.mkdir(parents=True,exist_ok=True)
def long_tone(path):
    container=q.av.open(str(path),'w',format='ipod');stream=container.add_stream('aac',rate=16000);stream.layout='mono';stream.bit_rate=48000
    total=45*16000
    for start in range(0,total,1024):
        n=min(1024,total-start);frame=q.av.AudioFrame(format='s16',layout='mono',samples=n);frame.sample_rate=16000;frame.pts=start;frame.time_base=Fraction(1,16000)
        frame.planes[0].update(struct.pack('<'+'h'*n,*[round(7000*math.sin(2*math.pi*440*(start+i)/16000)) for i in range(n)]))
        for packet in stream.encode(frame):container.mux(packet)
    for packet in stream.encode(None):container.mux(packet)
    container.close()

class Denial(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));mid=body['req']['param']['songmid'][0]
        raw=json.dumps({'code':0,'req':{'code':0,'data':{'retcode':0,'sip':['https://fixture.qq.com/'],'midurlinfo':[{'songmid':mid,'purl':'','result':0,'pneedbuy':1}]}}}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class Backend(a.Backend):
    deny=False
    def open_request(self,url,method,headers,body,maximum,timeout):
        if self.deny and body and json.loads(body).get('req',{}).get('module','').startswith('vkey.'):
            return pc.Backend.open_request(self,self.denial_url,method,headers,body,maximum,timeout)
        return super().open_request(url,method,headers,body,maximum,timeout)

def main():
    q.OUT=OUT;q.tone=long_tone;fixture=a.Fixture();h=None;checks=[]
    denial=http.server.ThreadingHTTPServer(('127.0.0.1',0),Denial);threading.Thread(target=denial.serve_forever,daemon=True).start()
    report={'passed':False,'physical_h1':False,'physical_esp32':False,'method':'linked native MIPS UI/network/MOV/AAC/ring; synthetic account/media/HTTP; modeled input and filesystem','checks':checks}
    def passed(text):checks.append(text);print('PASS',text,flush=True)
    try:
        h=a.Harness(fixture);m=h.m;h.backend.close();backend=Backend(fixture);backend.denial_url='http://127.0.0.1:'+str(denial.server_port);h.backend=backend;h.bridge.server=pc.Server(backend,h.audio)
        # The new peer must perform its own real HELLO/CAPS, as on reconnect.
        m.call('qm_net_reset')
        def key(*keys):
            h.until(lambda:not m.word('busy'));h.key(*keys)
        def title():return q.TRACK.unpack(m.get(m.symbols['qm_current'],q.TRACK.size))[3].split(b'\0')[0].decode()
        def song(i):return q.TRACK.unpack(m.get(m.symbols['qm_songs']+i*q.TRACK.size,q.TRACK.size))
        def tap(x,y,view):
            h.until(lambda:not m.word('busy'));before=m.word('inputs');m.events.extend([(11,0,x,y),(8,0,x,y)])
            h.until(lambda:m.state()['view']==view and m.completed_inputs>before)
        assert m.state()['view']==3;m.call('qm_paint');m.screenshot('01-home.png');passed('startup uses dedicated homepage; no hot-chart header or chart selection')
        key(13);assert m.state()['view']==0 and song(1)[-1]==1;m.screenshot('02-member-catalog.png')
        key(27,25);assert not m.play()['ready'] and '授权' in m.notice();passed('catalog member tag remains metadata; anonymous member request is blocked')
        fixture.confirm=True;key(8,1);h.until(lambda:m.account()['logged']==1);key(24)
        assert song(1)[-1]==1;key(25);h.until(lambda:m.play()['ms']>=300)
        assert m.play()['playing'] and song(1)[-1]&4;current=title();sessions=len(h.audio.sessions);before=m.play()['ms']
        key(24);assert m.state()['view']==0 and m.play()['playing'];h.until(lambda:m.play()['ms']>before+100)
        m.screenshot('03-verified-playing-list.png');passed('successful account playback marks only the verified track playable; back to list preserves advancing PCM')
        before=m.word('inputs');m.events.extend([(11,0,240,217),(12,0,240,125),(8,0,240,125)])
        h.until(lambda:m.word('list_offset')>30 and not m.word('pen_active'));assert m.word('inputs')==before and m.play()['playing']
        tap(75,160,1);assert title()==current and len(h.audio.sessions)==sessions;m.screenshot('04-return-to-player.png')
        passed('list drag remains a scroll; touching Now Playing returns to same song/session without reopening AAC')
        key(24);tap(75,70,3);assert m.play()['playing'] and len(h.audio.sessions)==sessions;m.screenshot('05-home-playing.png')
        passed('homepage navigation keeps background audio and displays a current-track return card')
        fixture.tracks[2]['songname']='浏览后新列表的歌曲';key(13,35);assert m.state()['view']==0 and m.word('page')==2 and m.play()['playing']
        assert song(1)[-1]&4 and title()==current;key(31,36);h.until(lambda:m.play()['pcm_bytes']>16000)
        assert title()=='测试歌曲 00';passed('pagination keeps current playback; Next uses captured playback queue rather than newly browsed songs')
        key(24);fixture.confirm=False;before=m.play()['ms'];key(8,1);h.until(lambda:m.account()['state']==3)
        h.until(lambda:m.play()['ms']>before+100 or m.play()['error']);assert m.play()['playing'] and not m.play()['error'];key(24)
        passed('QR HTTP request/polling coexist with advancing audio through completed RPC boundaries')
        before_title=title();key(9);h.until(lambda:m.play()['pcm_bytes']>16000);assert m.play()['playing'] and title()==before_title
        passed('native input safely bookmarks current song and restores playback before loading search results')
        backend.deny=True;key(27,25);assert m.play()['error'] and not song(1)[-1]&4;assert '授权' in m.notice();backend.deny=False
        passed('logged-in provider denial stays an explicit error and never invents playable permission')
        key(24,8,33);h.until(lambda:not m.account()['logged']);key(24)
        assert all(not song(i)[-1]&4 for i in range(m.state()['count']));m.screenshot('06-logged-out-list.png')
        passed('logout invalidates account-specific playable markers in lists and captured queue')
        h.close();h=None;report['passed']=True
    finally:
        if h:
            report['failure']={'state':h.m.state(),'play':h.m.play(),'account':h.m.account(),'notice':h.m.notice(),'pc':hex(h.m.pc),'invalid':h.m.invalid};h.m.screenshot('failure.png');h.backend.close();h.audio.close()
        denial.shutdown();denial.server_close();fixture.close()
        report['sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/'build/h1-qqmusic/H1QQMusicDbg.elf',ROOT/'dist/H1QQMusicDbg.bda')}
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS',len(checks),'navigation/background/rights groups; no physical device claim')
if __name__=='__main__':main()
