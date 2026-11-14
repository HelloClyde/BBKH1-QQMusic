"""Execute linked MIPS login/UI/storage and real generic HTTP with synthetic accounts.
No real account, phone approval, H1 timing or ESP hardware is claimed.
"""
from pathlib import Path
import hashlib,http.server,io,json,struct,threading,time,urllib.parse
from PIL import Image,ImageDraw
from unicorn.mips_const import UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_V0,UC_MIPS_REG_PC,UC_MIPS_REG_RA
from support import music as q
from support.mailbox import MailboxBridge
from support import http_peer as pc

ROOT=q.ROOT;OUT=ROOT/'build/qqmusic/accounts-0.1.9';OUT.mkdir(parents=True,exist_ok=True)
PATHS=('A:\\QQMusic.auth0','A:\\QQMusic.auth1')

class Fixture(q.Fixture):
    def __init__(self):
        super().__init__();self.confirm=False;self.expired=False;self.profile_expired=False;self.refresh_ok=True;self.seen=[]
        self.tracks[0]['songname']='夜に駆ける・ありがとう ｶﾀｶﾅ';self.tracks[0]['singer']=[{'name':'日本語テスト'}]
        image=Image.new('RGB',(132,132),'white');draw=ImageDraw.Draw(image)
        # Test image is a marked fixture, not a scannable authorization token.
        for y in range(12,120,4):
            for x in range(12,120,4):
                if (x*y+x+y)%7<3:draw.rectangle((x,y,x+3,y+3),fill='black')
        b=io.BytesIO();image.save(b,'PNG');self.qr=b.getvalue();owner=self
        class Auth(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):self.body=self.rfile.read(int(self.headers.get('Content-Length',0)));self.do_GET()
            def do_GET(self):
                u=urllib.parse.urlsplit(self.path);path=u.path;body=getattr(self,'body',b'');fields=[];status=200;kind='application/json'
                owner.seen.append((path,self.command,dict(self.headers),body))
                if path.endswith('ptqrshow'):
                    raw=owner.qr;kind='image/png';fields=[('Set-Cookie','qrsig=synthetic-signature; Expires=Wed, 01 Jan 2031 00:00:00 GMT; HttpOnly'),('Set-Cookie','aux=fixture; Secure')]
                elif path.endswith('ptqrlogin'):
                    assert 'qrsig=synthetic-signature' in self.headers.get('Cookie','')
                    assert urllib.parse.parse_qs(u.query)['ptqrtoken']==[str(qhash('synthetic-signature',0))]
                    code='65' if owner.expired else '0' if owner.confirm else '67'
                    raw=("ptuiCB('%s','0','https://ssl.ptlogin2.graph.qq.com/check_sig?uin=12345&service=ptqrlogin&ptsigx=synthetic-sig&s_url=x','0','fixture','Test')"%code).encode()
                elif path.endswith('check_sig'):
                    raw=b'';status=302;fields=[('Set-Cookie','p_skey=synthetic-skey; HttpOnly'),('Set-Cookie','p_uin=12345; Secure'),('Location','https://graph.qq.com/unused')]
                elif path.endswith('/authorize'):
                    form=urllib.parse.parse_qs(body.decode());assert form['g_tk']==[str(qhash('synthetic-skey',5381))]
                    assert 'p_skey=synthetic-skey' in self.headers.get('Cookie','')
                    raw=b'';status=302;fields=[('Location','https://y.qq.com/portal/wx_redirect.html?code=synthetic-code&state=state')]
                elif path.endswith('/qrconnect') and '/connect/l/' not in path:raw=b'<img src="/connect/qrcode/fixture-uuid"><script src="?uuid=fixture-uuid"></script>'
                elif '/connect/qrcode/' in path:raw=owner.qr;kind='image/png'
                elif '/connect/l/qrconnect' in path:
                    raw=("window.wx_errcode=%d;window.wx_code='%s'"%(402 if owner.expired else 405 if owner.confirm else 404,'synthetic-wx-code' if owner.confirm else '')).encode()
                elif path.endswith('musicu.fcg'):
                    data=json.loads(body);param=data['req']['param'];mode=param.get('loginMode');type_=data['comm']['tmeLoginType']
                    assert mode==2 or param['code'] in ('synthetic-code','synthetic-wx-code')
                    value={'code':104401} if mode==2 and not owner.refresh_ok else dict(code=0,str_musicid='12345',musickey=('W_X' if type_==1 else 'Q_Q')+'synthetic-music-key',refresh_key='synthetic-refresh',refresh_token='synthetic-refresh-token',loginType=type_,nickname='日本語・テスト')
                    raw=json.dumps({'code':0,'req':{'code':0,'data':value}},ensure_ascii=False).encode()
                elif path.endswith('fcg_get_profile_homepage.fcg'):
                    assert 'qqmusic_uin=12345' in self.headers.get('Cookie','');raw=json.dumps({'code':1000} if owner.profile_expired else {'code':0,'data':{'nickname':'日本語・テスト'}},ensure_ascii=False).encode()
                else:raise AssertionError('Unexpected fixture path '+path)
                self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
                for name,value in fields:self.send_header(name,value)
                self.end_headers();self.wfile.write(raw)
        self.auth=http.server.ThreadingHTTPServer(('127.0.0.1',0),Auth);threading.Thread(target=self.auth.serve_forever,daemon=True).start();self.auth_base='http://127.0.0.1:'+str(self.auth.server_port)
    def close(self):self.auth.shutdown();self.auth.server_close();super().close()

def qhash(s,seed):
    for byte in s.encode():seed=(seed*33+byte)&0xffffffff
    return seed&0x7fffffff

class Backend(q.Backend):
    def mapped(self,url):
        u=urllib.parse.urlsplit(url)
        if u.hostname in ('ssl.ptlogin2.qq.com','ssl.ptlogin2.graph.qq.com','graph.qq.com','open.weixin.qq.com','lp.open.weixin.qq.com','c6.y.qq.com'):return self.fixture.auth_base+u.path+('?' + u.query if u.query else '')
        return super().mapped(url)
    def open_request(self,url,method,headers,body,maximum,timeout):
        if urllib.parse.urlsplit(url).hostname=='u.y.qq.com' and json.loads(body).get('req',{}).get('module') in ('music.login.LoginServer','QQConnectLogin.LoginServer'):
            return pc.Backend.open_request(self,self.fixture.auth_base+'/cgi-bin/musicu.fcg',method,headers,body,maximum,timeout)
        return super().open_request(url,method,headers,body,maximum,timeout)

class Model(q.Model):
    def __init__(self):
        self.fail_write=False;super().__init__();self.install(0x80030000,0x24,0x80e20100,'remove')
    def hook(self,kind):
        if kind not in ('remove','fwrite'):return super().hook(kind)
        normal=super().hook(kind) if kind=='fwrite' else None
        def run(u,address,size,data):
            if kind=='remove':
                name=self.cstring(u.reg_read(UC_MIPS_REG_A0),'gbk');assert name in PATHS;self.files.pop(name,None);value=0
            elif self.fail_write:value=0
            else:return normal(u,address,size,data)
            u.reg_write(UC_MIPS_REG_V0,value);u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
        return run
    def account(self):
        raw=self.get(self.symbols['qm_account'],240);values=struct.unpack_from('<4I',raw)
        return dict(zip(('state','kind','logged','error'),values),nickname=raw[16:112].split(b'\0')[0].decode(),message=raw[112:240].split(b'\0')[0].decode())

class Harness(q.Harness):
    def __init__(self,fixture,files=None):
        self.m=Model();self.m.files=dict(files or {});self.bridge=None;self.fixture=fixture
        self.until(lambda:struct.unpack('<I',self.m.get(self.m.symbols['h1net_debug_mailbox']+16,4))[0]==1)
        self.bridge=MailboxBridge(self.m,ROOT/'dist/H1QQMusicDbg.build.json');self.bridge.backend.close()
        self.backend=Backend(fixture);self.audio=q.Audio();self.bridge.server=pc.Server(self.backend,self.audio)
        self.until(lambda:self.m.word('qm_connection_status')==3)
    def close(self):
        self.m.allow_exit=True;self.m.keys.extend([24,24]);self.until(lambda:self.m.pc==self.m.stop)
        assert not self.m.drawing and not self.m.allocations and not self.m.invalid and not self.m.handles
        assert all(c['path'] in PATHS or c['path']=='A:\\QQMusic.cfg' for c in self.m.file_calls)
        self.backend.close();self.audio.close()

def main():
    q.OUT=OUT;checks=[];report={'passed':False,'physical_h1':False,'physical_esp32':False,'method':'real linked MIPS application; synthetic provider and filesystem/mixer boundaries','checks':checks};h=None;fixture=Fixture()
    def passed(text):checks.append(text);print('PASS',text,flush=True)
    try:
        h=Harness(fixture);m=h.m
        assert m.state()['count']==0 and not m.word('inputs');m.screenshot('01-connected.png');passed('automatic HELLO/CAPS/STATUS detects connected Wi-Fi before any key')
        h.key(13);m.screenshot('02-japanese.png')
        # Confirm every requested character resolves to a non-fallback native glyph.
        count=json.loads((ROOT/'assets/font.json').read_text())['glyphs']
        codes=list(struct.unpack('<%uH'%count,m.get(m.symbols['qm_font_cp'],count*2)))
        assert all(ord(c) in codes for c in '夜に駆けるありがとうｶﾀｶﾅ日本語')
        h.key(8,1);h.until(lambda:m.account()['state']==3);m.screenshot('03-qq-scan.png');assert m.word('qm_account_qr_width')==132
        fixture.confirm=True;h.until(lambda:m.account()['logged']==1);assert m.account()['kind']==2
        saved=dict(m.files);assert saved;passed('QQ QR, signature cookie, callback, OAuth redirect and local verified login file complete')
        h.close();h=None
        h=Harness(fixture,saved);m=h.m;h.until(lambda:m.account()['logged']==1);assert m.account()['nickname']=='日本語・テスト';passed('restart reads H1 login file and validates saved session with provider')
        # Inspect outputs of the real application request decorator, using only synthetic secrets.
        def decorate(url):
            addresses=(0x81050000,0x81051000,0x81052000,0x81053000,0x81053010,0x81053020)
            raw=b'{"comm":{},"req":{"module":"vkey.GetVkeyServer","param":{"uin":"0"}}}'
            m.put(addresses[0],url.encode()+b'\0');m.put(addresses[1],b'Referer: https://y.qq.com/\0');m.put(addresses[2],raw)
            e=m.call('qm_account_authorize',addresses[0],addresses[1],addresses[2],len(raw),*addresses[3:]);hp,bp,n=[struct.unpack('<I',m.get(a,4))[0] for a in addresses[3:]]
            headers=m.cstring(hp) if hp else '';body=json.loads(m.get(bp,n)) if bp else None
            for pointer in (hp,bp):
                if pointer:m.call('free',pointer)
            return e,headers,body
        e,headers,body=decorate('https://u.y.qq.com/cgi-bin/musicu.fcg');assert e==1 and 'qqmusic_uin=12345' in headers and body['req']['param']['uin']=='12345',(e,'qqmusic_uin=12345' in headers,body)
        for url in ('https://u.y.qq.com.evil.test/cgi-bin/musicu.fcg','https://cdn.example.test/file','http://u.y.qq.com/cgi-bin/musicu.fcg'):
            assert decorate(url)==(0,'',None)
        passed('H1 attaches saved account to trusted music API only; CDN/arbitrary hosts receive no cookie')
        h.key(8,33);assert not m.account()['logged'];tombstone=dict(m.files);h.close();h=None
        h=Harness(fixture,tombstone);m=h.m;assert not m.account()['logged'];passed('logout writes durable verified tombstone; restart remains signed out')
        fixture.confirm=False;h.key(8,2);h.until(lambda:m.account()['state']==3);m.screenshot('04-wechat-scan.png')
        fixture.confirm=True;h.until(lambda:m.account()['logged']==1);assert m.account()['kind']==1;wechat=dict(m.files);passed('WeChat UUID/image, phone confirmation callback and credential persistence complete')
        h.close();h=None
        fixture.profile_expired=True;h=Harness(fixture,wechat);m=h.m;h.until(lambda:m.account()['logged']==1);passed('expired saved login refreshes using application-owned refresh credential')
        h.key(8,33);fixture.confirm=False;fixture.expired=True;h.key(1);h.until(lambda:m.account()['state']==5);passed('expired QR is displayed as expired and permits a new QR request')
        fixture.expired=False;h.key(4);h.until(lambda:m.account()['state']==3);m.fail_write=True;fixture.confirm=True;h.until(lambda:m.account()['state']==6);assert not m.account()['logged'];m.fail_write=False;passed('storage failure never reports a saved login; previous logout stays intact')
        h.close();h=None;fixture.profile_expired=False
        h=Harness(fixture);m=h.m;h.key(13,25);h.until(lambda:m.play()['ms']>=250 and m.word('queued')<7000)
        before=m.play()['ms'];_,descriptor,cursor,_,_,_=struct.unpack('<6I',m.get(m.node,24));base=struct.unpack('<I',m.get(descriptor,4))[0];pos=(cursor-base)//2
        consumed=m.word('queued')+128;m.put(m.node+8,struct.pack('<I',base+2*((pos+consumed)%8192)));m.hw_samples+=consumed
        h.until(lambda:m.word('underruns')>0);h.until(lambda:m.play()['ms']>before+100 or m.play()['error'])
        assert not m.play()['error'] and m.play()['ms']>before+100;passed('real ring observes a forced underrun; application keeps decoder/demux intact and actual retired PCM advances progress again')
        h.close();h=None;report['passed']=True
    finally:
        if h:
            report['failure']={'state':h.m.state(),'play':h.m.play(),'account':h.m.account(),'pc':hex(h.m.pc),'invalid':h.m.invalid};h.m.screenshot('failure.png');h.backend.close();h.audio.close()
        fixture.close();report['sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/'build/qqmusic/H1QQMusicDbg.elf',ROOT/'dist/H1QQMusicDbg.bda')}
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS',len(checks),'application login/recovery groups; synthetic accounts only')

if __name__=='__main__':main()
