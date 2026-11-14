"""Real linked Wi-Fi Setup MIPS UI; modeled H1 firmware and Wi-Fi peer, no devices."""
from pathlib import Path
import hashlib,json,struct,sys,time
from PIL import Image
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS32,UC_MODE_LITTLE_ENDIAN,UC_HOOK_BLOCK,UC_HOOK_CODE,UC_HOOK_MEM_INVALID
from unicorn.mips_const import UC_MIPS_REG_SP,UC_MIPS_REG_RA,UC_MIPS_REG_PC,UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_V0
from test_h1_news_model import Model as NewsModel
from h1_wifi_debug import DebugBridge
import h1_wifi_pc as pc

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/h1-wifi/settings/model'
NAMES=('magic','schema','view','capable','usb','count','selected','scanning','active','queued','length','reveal','manual','outcome','error','connected','operation','scan_state','inputs','presents','result','reuse','panic','closing')

class Model(NewsModel):
    def __init__(self,elf_path):
        self.u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN);self.u.mem_map(0,64*1024*1024)
        self.start=self.timer_origin=time.monotonic();self.timer_frozen=0;self.timer_running=False
        self.keys=[];self.events=[];self.pen=(0,0);self.fb=0x81200000;self.stop=0x83bff000;self.allow_exit=False;self.drawing=False;self.frames=0
        self.allocations={};self.blocks=[(0x81400000,16*1024*1024)];self.minimum_stack=0xffffffff
        self.files={};self.handles={};self.next_handle=1;self.file_calls=[];self.invalid=None;self.budget=0
        self.native_buffer_calls=self.blit_calls=0
        with elf_path.open('rb') as stream:
            elf=ELFFile(stream)
            for segment in elf.iter_segments():
                if segment['p_type']=='PT_LOAD':self.put(segment['p_vaddr'],segment.data())
            self.symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        def boundary(u,address,size,data):
            if self.budget<=0:u.emu_stop();return
            self.budget-=max(size//4,1)
        self.u.hook_add(UC_HOOK_BLOCK,boundary)
        table=0x80010000;self.put(0x83c00004,struct.pack('<I',table))
        for i,(offset,kind) in enumerate(((0x714,'start'),(0x718,'stop'),(0x71c,'time'),(0x84c,'open'),(0x850,'close'),(0x8f4,'buffer'),(0x750,'keys'),(0x6d8,'raw-time'))):
            self.install(table,offset,0x80e00000+i*16,kind)
        coordinate=0x80e00300;self.put(table+0x6c0,struct.pack('<I',coordinate))
        # Signature-compatible modeled calibrated getter; reads two test input u16s.
        self.put(coordinate,struct.pack('<17I',0x27bdffa8,0xafbf0050,0xafb60048,0xafb7004c,0x00a0b821,0x0080b021,
            0x3c088109,0x95090000,0xa4890000,0x95090002,0xa4a90000,
            0x8fb60048,0x8fb7004c,0x8fbf0050,0x27bd0058,0x03e00008,0))
        memory=0x80020000;self.put(0x83c00010,struct.pack('<I',memory))
        for i,(offset,kind) in enumerate(((8,'alloc'),(12,'free'))):self.install(memory,offset,0x80e10000+i*16,kind)
        files=0x80030000;self.put(0x83c00008,struct.pack('<I',files))
        for i,kind in enumerate(('fopen','fclose','fread','fwrite','fseek','ftell')):self.install(files,i*4,0x80e20000+i*16,kind)
        for symbol,kind in (('fw_matches','fw'),('fw_delay','delay')):
            self.u.hook_add(UC_HOOK_CODE,self.hook(kind),begin=self.symbols[symbol],end=self.symbols[symbol])
        def invalid(u,access,address,size,value,data):self.invalid=[access,hex(address),size,hex(value)];return False
        self.u.hook_add(UC_HOOK_MEM_INVALID,invalid)
        self.pc=self.symbols['h1_bda_main'];self.u.reg_write(UC_MIPS_REG_SP,0x83b00000);self.u.reg_write(UC_MIPS_REG_RA,self.stop)
    def hook(self,kind):
        if kind not in ('keys','coordinate'):return super().hook(kind)
        def run(u,address,size,data):
            if kind=='coordinate':
                self.put(u.reg_read(UC_MIPS_REG_A0),struct.pack('<H',self.pen[0]));self.put(u.reg_read(UC_MIPS_REG_A1),struct.pack('<H',self.pen[1]))
            else:
                if self.events:
                    code,key,x,y=self.events.pop(0);self.pen=(x,y)
                    self.put(0x81090000,struct.pack('<2H',x,y))
                else:code,key=(9,self.keys.pop(0)) if self.keys else (-1,-1)
                self.put(u.reg_read(UC_MIPS_REG_A0),struct.pack('<i',code));self.put(u.reg_read(UC_MIPS_REG_A1),struct.pack('<i',key))
            u.reg_write(UC_MIPS_REG_V0,0);u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
        return run
    def state(self):return dict(zip(NAMES,struct.unpack('<24I',self.get(self.symbols['wifi_settings_state'],96))))
    def notice(self):return self.string('wifi_settings_notice',160)
    def screenshot(self,name):Image.frombytes('RGB',(480,272),self.get(self.fb,480*272*4),'raw','BGRX').save(OUT/name)

class Peer:
    """Deterministic peer fixture. Never stores or prints real user credentials."""
    def __init__(self):
        self.ready=False;self.seq=0;self.scan=0;self.scan_state=0;self.operation=0;self.outcome=0;self.error=0
        self.saved='Home-Old';self.current='Home-Old';self.connected=True;self.mode='success';self.ticks=0
        self.feature=True;self.malformed=False;self.requests=[];self.last_reuse=0
        self.aps=[('家庭路由器',-40,3,6),('Guest-Free',-55,0,1),('Legacy-WEP',-60,1,11)]
        self.aps += [('Test-%02d'%i,-65-i,3,6) for i in range(21)]
    def status(self):
        if self.scan_state==1:self.scan_state=2
        if self.outcome==5:
            self.ticks+=1
            if self.ticks>=3:self.saved=self.current='';self.connected=False;self.outcome=self.error=0
        if self.outcome==1:
            self.ticks+=1
            if self.ticks>=3 and self.mode!='pending':
                if self.mode=='success':self.outcome=2;self.error=0;self.saved=self.current=self.target;self.connected=True
                else:self.outcome=3;self.error={'auth':1,'timeout':3,'storage':5}[self.mode];self.current=self.saved;self.connected=bool(self.saved)
        a=self.current.encode();b=self.saved.encode()
        raw=struct.pack('<11I',1,self.operation,self.outcome,self.error,202 if self.error==1 else 0,int(self.connected),0x6401a8c0,(-45)&0xffffffff,self.scan,self.scan_state,len(self.aps) if self.scan_state==2 else 0)
        raw+=bytes([len(a)])+a.ljust(32,b'\0')+bytes([len(b)])+b.ljust(32,b'\0')
        return raw[:-1] if self.malformed else raw
    def dispatch(self,frame):
        op,seq,status,p=frame;error=0;data=b'';self.requests.append(op)
        if op==1 and not p:self.ready=True;self.seq=seq;data=pc.IDENTITY
        elif not self.ready:error=3
        elif seq!=(self.seq+1)&65535:error=1
        else:
            self.seq=seq
            if op==10:data=struct.pack('<4I',1,4,8*1024*1024,16 if self.feature else 0)
            elif op==22:
                self.scan+=1;self.scan_state=1;data=struct.pack('<I',self.scan)
            elif op==24:data=self.status()
            elif op==23:
                scan,offset=struct.unpack('<IH',p);assert scan==self.scan
                page=self.aps[offset:offset+12];data=struct.pack('<IBBBB',scan,2,len(page),len(self.aps),0)
                for ssid,rssi,auth,channel in page:
                    raw=ssid.encode();data+=struct.pack('<BbBB',len(raw),rssi,auth,channel)+raw.ljust(32,b'\0')
            elif op==25:
                sn,pn,auth,reuse=p[:4];assert len(p)==4+sn+pn and (auth==0 and pn==0 or reuse and pn==0 or 8<=pn<=63)
                self.target=p[4:4+sn].decode();self.last_reuse=reuse;self.operation+=1;self.outcome=1;self.error=0;self.ticks=0
                data=struct.pack('<I',self.operation)
            elif op==26:self.operation+=1;self.outcome=5;self.error=0;self.ticks=0;data=struct.pack('<I',self.operation)
            elif op==27:
                assert struct.unpack('<I',p)[0]==self.operation;self.outcome=4;self.current=self.saved;self.connected=bool(self.saved)
            else:error=1
        return pc.encode(op|128,seq,data if not error else b'',error)

class Harness:
    def __init__(self,feature=True):
        self.m=Model(ROOT/'build/h1-wifi/settings/H1WiFiSetupDbg.elf');self.peer=Peer();self.peer.feature=feature
        self.bridge=None
        self.until(lambda:self.m.get(self.m.symbols['h1net_debug_mailbox']+16,4)==struct.pack('<I',1))
        self.bridge=DebugBridge(self.m,ROOT/'dist/H1WiFiSetupDbg.build.json');self.bridge.backend.close();self.bridge.server=self.peer
    def until(self,predicate,timeout=12):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.m.step()
            if self.bridge and not self.m.allow_exit:self.bridge.service()
            if predicate():return
        raise AssertionError({'state':self.m.state(),'notice':self.m.notice(),'requests':self.peer.requests[-12:]})
    def key(self,*values):
        target=self.m.word('inputs')+len(values);self.m.keys.extend(values)
        self.until(lambda:not self.m.keys and self.m.state()['inputs']>=target)
    def idle(self):self.until(lambda:self.m.state()['active']==0 and self.m.state()['queued']==0)
    def tap(self,x,y):
        self.m.events.extend([(11,0,x,y),(8,0,x,y)]);self.until(lambda:not self.m.events)
        frame=self.m.word('presents');self.until(lambda:self.m.state()['presents']>frame)
    def scanned(self,target=1):
        self.until(lambda:self.m.state()['capable'] and self.m.state()['count']==24 and not self.m.state()['scanning'] and self.peer.scan>=target and self.peer.scan_state==2)
        self.idle()
    def connect(self,mode='success'):
        self.peer.mode=mode;self.key(25);self.until(lambda:self.m.state()['view']==1)
        self.key(1,2,3,4,5,6,7,29);assert self.m.state()['length']==8
        self.key(25);self.until(lambda:self.m.state()['outcome']==1 and self.m.state()['view']==2)
        assert self.m.state()['length']==0
    def close(self):
        # Return through the real foreground cleanup, rather than stopping Unicorn.
        self.m.allow_exit=True;self.m.keys.extend([24,24]);self.until(lambda:self.m.pc==self.m.stop)
        assert not self.m.drawing and not self.m.allocations and not self.m.invalid and not self.m.file_calls
        assert self.m.get(self.m.symbols['editor'],64)==bytes(64)
        assert self.m.get(self.m.symbols['rpc'],528)==bytes(528)

def main():
    OUT.mkdir(parents=True,exist_ok=True);checks=[];h=None
    report={'passed':False,'physical_h1':False,'physical_esp32':False,'method':'real linked MIPS UI/editor/client/heap; Wi-Fi peer and H1 firmware modeled','checks':checks}
    try:
        h=Harness();h.scanned();h.m.screenshot('01-scan.png');checks.append('24 APs including Chinese SSID, two protocol pages; automatic scan and physical-key navigation')
        h.tap(450,14);assert h.m.state()['selected']==5;h.tap(370,14);assert h.m.state()['selected']==0
        # Actual compiled C helpers, boundary inputs, and memory clearing.
        m=h.m;addr=0x81080000;m.put(addr,bytes(96));m.call('wifi_editor_clear',addr,63)
        for i in range(63):assert m.call('wifi_editor_insert',addr,ord('!'))==1
        assert m.call('wifi_editor_insert',addr,ord('!'))==0
        m.call('wifi_editor_delete',addr);assert m.get(addr+62,2)==b'\0\0'
        m.call('wifi_editor_clear',addr,32);assert m.get(addr,64)==bytes(64)
        sn=0x81080100;pn=0x81080200;m.put(sn,b'S'*33);m.put(pn,b'p'*64)
        for s,p,a,reuse,expected in ((32,8,3,0,1),(33,8,3,0,0),(1,7,3,0,0),(1,63,6,0,1),(1,64,3,0,0),(1,0,0,0,1),(1,8,0,0,0),(1,0,3,1,1),(1,8,1,0,0),(1,8,5,0,0)):
            assert m.call('h1wifi_credentials_valid',sn,s,pn,p,a,reuse)==expected
        checks.append('real C editor 63-byte cap/delete/clear; credentials SSID32/password8..63/open/reuse/unsupported boundaries')
        h.key(25);h.until(lambda:m.state()['view']==1);h.key(1,2,3);m.screenshot('02-password.png')
        h.key(25);assert m.state()['view']==1 and m.state()['length']==3
        h.key(24);h.key(27,27,25);assert '暂不支持' in m.notice();h.key(37,37)
        checks.append('short password stays in editor; Esc clears it; WEP rejected before transmitting credentials')
        h.key(25);h.tap(25,260);h.tap(20,119);assert m.state()['length']==1
        assert m.get(m.symbols['editor'],2)==b'!\0';h.tap(335,260);assert m.state()['reveal']==1
        h.tap(235,260);assert m.state()['length']==0;h.key(24)
        checks.append('calibrated touch boundary drives real page arrows, case toggle, symbol key, reveal and delete')
        h.connect();h.until(lambda:m.state()['outcome']==2);m.screenshot('03-connected.png');assert h.peer.saved=='家庭路由器'
        checks.append('connect progress then success status; editor/request password buffers cleared; success saved by peer fixture')
        h.key(24,25);assert m.state()['reuse']==1;h.key(25);h.until(lambda:m.state()['outcome']==2 and h.peer.last_reuse==1)
        checks.append('saved network uses reuse flag with no password returned to H1')
        for mode,error in (('auth',1),('timeout',3),('storage',5)):
            h.key(24);h.connect(mode);h.until(lambda:m.state()['outcome']==3 and m.state()['error']==error)
            assert h.peer.saved=='家庭路由器'
        m.screenshot('04-failed.png');checks.append('auth failure/timeout/storage failure show specific errors and peer retains old configuration')
        h.key(24);h.connect('pending');h.key(18);h.until(lambda:m.state()['outcome']==4)
        checks.append('cancel operation id is sent; cancelled status shown')
        h.key(11);h.until(lambda:m.state()['view']==3);m.screenshot('05-forget-confirm.png');h.key(24)
        assert h.peer.saved;h.key(9,11,25);h.until(lambda:not h.peer.saved and '已忘记' in m.notice())
        checks.append('forget requires explicit confirmation; Esc preserves saved network; confirm clears peer configuration')
        h.key(24,27,25);h.until(lambda:m.state()['view']==1);h.peer.mode='success';h.key(25)
        h.until(lambda:m.state()['outcome']==2);assert h.peer.saved=='Guest-Free'
        checks.append('open network connects with zero password bytes')
        h.key(24,13);h.until(lambda:m.state()['manual']==1);h.key(42,1,42,2,3,4,25)
        h.until(lambda:m.state()['view']==1 and not m.state()['manual']);h.key(43,1,2,3,4,5,6,7,29,25)
        h.until(lambda:m.state()['outcome']==2 and h.peer.saved=='Qwer')
        checks.append('manual hidden SSID, Shift case and Fn numeric passwords execute real key handlers')
        h.bridge.write_word(10,0);h.until(lambda:not m.state()['capable']);m.screenshot('06-disconnected.png')
        checks.append('disconnect clears editor and capability; shows reconnect instruction')
        h.bridge.write_word(10,h.bridge.session+1);h.scanned(2);h.peer.malformed=True
        h.until(lambda:not m.state()['capable']);assert 'USB通信失败' in m.notice()
        h.peer.malformed=False;h.key(4);h.scanned(3);checks.append('malformed status length rejects; explicit R retry re-handshakes and recovers')
        h.close();h=None
        h=Harness(False);h.until(lambda:'0.4.0' in h.m.notice());assert not h.m.state()['capable'] and 22 not in h.peer.requests
        h.m.screenshot('07-old-firmware.png');checks.append('old ESP feature bitmap prompts upgrade without scan/connect writes');h.close();h=None
        report['passed']=True
    finally:
        if h:report['failure_state']=h.m.state();report['failure_notice']=h.m.notice();h.m.screenshot('failure.png')
        paths=[ROOT/'dist/H1WiFiSetupDbg.bda',ROOT/'build/h1-wifi/settings/H1WiFiSetupDbg.elf',Path(__file__)]
        report['sha256']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS real MIPS Wi-Fi settings:',len(checks),'groups; no physical device acceptance')

if __name__=='__main__':main()
