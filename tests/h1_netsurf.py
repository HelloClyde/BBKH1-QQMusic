"""Execute the linked NetSurf MIPS BDA code; GUI/heap firmware modeled, engine real."""
from pathlib import Path
import json,struct,time,hashlib
from PIL import Image
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS32,UC_MODE_LITTLE_ENDIAN,UC_HOOK_CODE,UC_HOOK_BLOCK
from unicorn.mips_const import UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_SP,UC_MIPS_REG_RA,UC_MIPS_REG_PC,UC_MIPS_REG_V0
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'build/h1-netsurf';DEFAULT_ELF=OUT/'H1NetSurfDbg.elf'
class Model:
    _broken=False
    def __init__(self,elf_path=None):
        self.u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN);self.u.mem_map(0,64*1024*1024)
        self.start=time.monotonic();self.keys=[];self.texts=[];self.js_observed_frame=None;self.drawing=False;self.fb=0x81200000;self.stop=0x83bff000;self.allow_exit=False
        self.timer_origin=self.start;self.timer_frozen=0;self.timer_running=False;self.native_modal_count=0
        self.pcm=bytearray();self.audio_events=[]
        self.allocations={};self.blocks=[(0x81400000,16*1024*1024)];self.minimum_stack=0xffffffff
        with (elf_path or DEFAULT_ELF).open('rb') as f:
            elf=ELFFile(f)
            for p in elf.iter_segments():
                if p['p_type']=='PT_LOAD':self.put(p['p_vaddr'],p.data())
            self.symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        self.pc=self.symbols['h1_bda_main'];self.u.reg_write(UC_MIPS_REG_SP,0x83b00000);self.u.reg_write(UC_MIPS_REG_RA,self.stop)
        self.budget=0
        def boundary(u,address,size,data):
            if self.budget<=0:u.emu_stop();return
            self.budget-=max(size//4,1)
        self.u.hook_add(UC_HOOK_BLOCK,boundary)
        table=0x80010000;self.put(0x83c00004,struct.pack('<I',table))
        entries=[(0x714,'start'),(0x718,'stop'),(0x71c,'time'),(0x84c,'open'),(0x850,'close'),(0x8f4,'buffer'),(0x750,'keys')]
        for i,(offset,kind) in enumerate(entries):self.install(table,offset,0x80e00000+i*16,kind)
        mem=0x80020000;self.put(0x83c00010,struct.pack('<I',mem))
        for i,(offset,kind) in enumerate([(8,'alloc'),(12,'free')]):self.install(mem,offset,0x80e10000+i*16,kind)
        for name,kind in [('fw_matches','fw'),('fw_delay','delay'),('bu_native_input_raw','native-modal')]:self.u.hook_add(UC_HOOK_CODE,self.hook(kind),begin=self.symbols[name],end=self.symbols[name])
        for name,kind in [('gba_audio_open','audio-open'),('gba_audio_write','audio-write'),('gba_audio_wait','audio-wait'),('gba_audio_pause','audio-pause'),('gba_audio_resume','audio-resume'),('gba_audio_close','audio-close'),('gba_audio_set_volume','audio-volume')]:
            if name in self.symbols:self.u.hook_add(UC_HOOK_CODE,self.hook(kind),begin=self.symbols[name],end=self.symbols[name])
        def rendered_text(u,a,size,data):
            pointer,n=struct.unpack('<2I',self.get(u.reg_read(UC_MIPS_REG_SP)+16,8))
            if n<=4096:
                text=self.get(pointer,n).decode('utf-8','replace');self.texts.append(text)
                if text=='JavaScript DOM works' and self.js_observed_frame is None:self.js_observed_frame=self.word('h1ns_present_count')
        self.u.hook_add(UC_HOOK_CODE,rendered_text,begin=self.symbols['plot_text'],end=self.symbols['plot_text'])
    def install(self,table,offset,address,kind):
        self.put(table+offset,struct.pack('<I',address));self.put(address,b'\x08\x00\xe0\x03\0\0\0\0');self.u.hook_add(UC_HOOK_CODE,self.hook(kind),begin=address,end=address)
    def put(self,a,data):self.u.mem_write(a&0x1fffffff,bytes(data))
    def get(self,a,n):return bytes(self.u.mem_read(a&0x1fffffff,n))
    def word(self,name):return struct.unpack('<I',self.get(self.symbols[name],4))[0]
    def string(self,name,limit=1024):return self.get(self.symbols[name],limit).split(b'\0',1)[0].decode('utf-8','replace')
    def allocate(self,n):
        n=(n+15)&~15
        for i,(a,size) in enumerate(self.blocks):
            if size>=n:
                self.blocks.pop(i)
                if size>n:self.blocks.insert(i,(a+n,size-n))
                self.allocations[a]=n;return a
        return 0
    def release(self,a):
        if not a:return
        n=self.allocations.pop(a);self.blocks.append((a,n));self.blocks.sort();merged=[]
        for a,n in self.blocks:
            if merged and merged[-1][0]+merged[-1][1]==a:merged[-1]=(merged[-1][0],merged[-1][1]+n)
            else:merged.append((a,n))
        self.blocks=merged
    def hook(self,kind):
        def run(u,a,size,data):
            value=0
            if kind=='fw':value=1
            elif kind=='start':self.timer_origin=time.monotonic();self.timer_frozen=0;self.timer_running=True
            elif kind=='stop':
                if self.timer_running:self.timer_frozen=int((time.monotonic()-self.timer_origin)*1000)
                self.timer_running=False
            elif kind=='time':value=int((time.monotonic()-self.timer_origin)*1000) if self.timer_running else self.timer_frozen
            elif kind=='raw-time':value=int((time.monotonic()-self.start)*80)&0xffffffff
            elif kind=='native-modal':self.timer_running=False;self.native_modal_count+=1
            elif kind.startswith('audio-'):
                if kind=='audio-write':
                    frames=u.reg_read(UC_MIPS_REG_A1);assert frames<=48000;self.pcm.extend(self.get(u.reg_read(UC_MIPS_REG_A0),frames*4));value=frames
                else:
                    self.audio_events.append((kind,u.reg_read(UC_MIPS_REG_A0)))
                    value=1 if kind in ('audio-open','audio-resume') else 0
            elif kind=='alloc':value=self.allocate(u.reg_read(UC_MIPS_REG_A0))
            elif kind=='free':self.release(u.reg_read(UC_MIPS_REG_A0))
            elif kind=='open':assert not self.drawing;self.drawing=True;value=1
            elif kind=='close':assert self.drawing;self.drawing=False
            elif kind=='buffer':assert self.drawing;self.put(u.reg_read(UC_MIPS_REG_A0),struct.pack('<6H',0,480,272,1920,0,32));value=self.fb
            elif kind=='keys':
                code,key=(9,self.keys.pop(0)) if self.keys else (-1,-1)
                self.put(u.reg_read(UC_MIPS_REG_A0),struct.pack('<i',code));self.put(u.reg_read(UC_MIPS_REG_A1),struct.pack('<i',key))
            u.reg_write(UC_MIPS_REG_V0,value);u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
        return run
    def step(self):
        # End slices at basic-block boundaries, preserving MIPS branch-delay semantics.
        self.budget=100000;self.u.emu_start(self.pc,self.stop);self.pc=self.u.reg_read(UC_MIPS_REG_PC)
        sp=self.u.reg_read(UC_MIPS_REG_SP)
        if self.symbols['__app_stack_bottom']<=sp<=self.symbols['__app_stack_top']:self.minimum_stack=min(self.minimum_stack,sp)
        if self.pc==self.stop and not self.allow_exit:raise RuntimeError('NetSurf returned before acceptance')
    def screenshot(self,name):Image.frombytes('RGB',(480,272),self.get(self.fb,480*272*4),'raw','BGRX').save(OUT/name)
    def read_memory(self,address,n):self.step();return self.get(address,n)
    def write_memory(self,address,data):self.put(address,data)
    def press(self,keys,ticks=2):
        values={'ENTER':25,'UP':37,'DOWN':27,'LEFT':40,'RIGHT':35,'PAGE_DOWN':22,'PAGE_UP':15,'BACK':41,'B':20,'R':4,'H':13,'ESCAPE':24,'LEFT_ALT':26}
        self.keys.extend(values[k] for k in keys);self.step()
    def log(self):return self.get(self.symbols['h1ns_log'],min(self.word('h1ns_log_size'),32767)).decode('utf-8','replace')

def main():
    m=Model();report=dict(passed=False,physical_h1=False,method='real NetSurf and Duktape MIPS code, modeled H1 firmware',elf_sha256=hashlib.sha256(DEFAULT_ELF.read_bytes()).hexdigest())
    try:
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            m.step()
            if m.word('panic_code'):raise RuntimeError('NetSurf panic '+str(m.word('panic_code')))
            if m.js_observed_frame is not None and m.word('h1ns_present_count')>m.js_observed_frame and m.word('revision'):
                m.screenshot('netsurf-js.png');break
        else:raise TimeoutError('NetSurf JS/DOM page not complete; PC '+hex(m.pc)+' title '+m.string('title'))
        report.update(title=m.string('title'),rendered_text=m.texts,revision=m.word('revision'),peak_heap=m.word('h1ns_heap_peak'),stack_sample_headroom=m.minimum_stack-m.symbols['__app_stack_bottom'])
        m.allow_exit=True;m.keys.append(24)
        for i in range(5000):
            m.step()
            if m.pc==m.stop:break
        assert m.pc==m.stop and not m.allocations and not m.drawing,'NetSurf exit did not release H1 heap/window'
        report.update(passed=True,heap_released=True,window_released=True)
    except BaseException as e:
        report.update(error=str(e),pc=hex(m.u.reg_read(UC_MIPS_REG_PC)),title=m.string('title'),heap=m.word('h1ns_heap_live'),rendered_text=m.texts[-30:])
        raise
    finally:
        m.screenshot('netsurf-last.png');(OUT/'model-log.txt').write_text(m.log(),encoding='utf-8');(OUT/'model-tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS real NetSurf MIPS HTML/CSS + Duktape JS/DOM visible text update; heap and window released')
if __name__=='__main__':main()
