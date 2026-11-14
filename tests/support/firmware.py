"""Scripted H1 firmware services for the actual linked music MIPS binary."""
import io,struct,time
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_MIPS,UC_MODE_MIPS32,UC_MODE_LITTLE_ENDIAN,UC_HOOK_BLOCK,UC_HOOK_CODE,UC_HOOK_MEM_INVALID
from unicorn.mips_const import UC_MIPS_REG_SP,UC_MIPS_REG_RA,UC_MIPS_REG_PC,UC_MIPS_REG_A0,UC_MIPS_REG_A1,UC_MIPS_REG_A2,UC_MIPS_REG_A3,UC_MIPS_REG_V0

class FirmwareBase:
    def cstring(self,address,encoding='utf-8',limit=4096):
        return self.get(address,limit).split(b'\0',1)[0].decode(encoding,'strict')
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
        if self.pc==self.stop and not self.allow_exit:raise RuntimeError('Music returned before acceptance')
    def write_memory(self,address,data):self.put(address,data)

class FileServices(FirmwareBase):
    def hook(self, kind):
        if kind not in ('fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'mkdir', 'remove', 'buffer', 'blit', 'present'):
            return super().hook(kind)
        def run(u, address, size, unused):
            args = [u.reg_read(reg) for reg in (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3)]
            value = 0
            if kind=='mkdir':
                path=self.cstring(args[0],'gbk');assert path=='A:\\飞天音乐'
                self.mkdir_calls.append(path)
                if self.fail_mkdir:value=-1
                else:self.directories.add(path)
            elif kind=='remove':
                path=self.cstring(args[0],'gbk');assert path in self.owned_paths
                self.files.pop(path,None)
            elif kind == 'buffer':
                assert self.drawing
                self.put(args[0], struct.pack('<6H', 0, 480, 272, 1920, 0, 32))
                self.frames += 1; self.native_buffer_calls += 1; value = self.fb
            elif kind == 'blit':
                self.blit_calls += 1
                raise AssertionError('SDK blit is unavailable in an active native game drawing context')
            elif kind == 'present':
                assert not self.drawing, 'normal SDK present used in native game context'
            elif kind == 'fopen':
                path, mode = self.cstring(args[0], 'gbk'), self.cstring(args[1])
                self.file_calls.append({'path': path, 'mode': mode})
                parent=path.rsplit('\\',1)[0]
                exists=parent in self.directories or any(p.startswith(parent+'\\') for p in self.files)
                if exists and (path in self.files or 'w' in mode):
                    value = self.next_handle; self.next_handle += 1
                    self.handles[value] = (path, mode, io.BytesIO(b'' if 'w' in mode else self.files[path]))
            elif kind == 'fclose':
                path, mode, handle = self.handles.pop(args[0])
                if 'w' in mode or '+' in mode: self.files[path] = handle.getvalue()
            elif kind in ('fread', 'fwrite'):
                handle = self.handles[args[3]][2]
                if kind == 'fread':
                    raw = handle.read(args[1]*args[2]); self.put(args[0], raw); value = len(raw)
                else: value = handle.write(self.get(args[0], args[1]*args[2]))
            elif kind == 'fseek':
                offset = args[1] if args[1] < 0x80000000 else args[1]-0x100000000
                value = self.handles[args[0]][2].seek(offset, args[2])
            elif kind == 'ftell': value = self.handles[args[0]][2].tell()
            u.reg_write(UC_MIPS_REG_V0, value); u.reg_write(UC_MIPS_REG_PC, u.reg_read(UC_MIPS_REG_RA))
        return run

class FirmwareModel(FileServices):
    def __init__(self,elf_path):
        self.u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN);self.u.mem_map(0,64*1024*1024)
        self.start=self.timer_origin=time.monotonic();self.timer_frozen=0;self.timer_running=False
        self.keys=[];self.events=[];self.pen=(0,0);self.fb=0x81200000;self.stop=0x83bff000;self.allow_exit=False;self.drawing=False;self.frames=0
        self.allocations={};self.blocks=[(0x81400000,16*1024*1024)];self.minimum_stack=0xffffffff
        self.files={};self.handles={};self.next_handle=1;self.file_calls=[];self.invalid=None;self.budget=0
        self.native_buffer_calls=self.blit_calls=0
        self.directories={'A:'};self.mkdir_calls=[];self.fail_mkdir=False
        self.owned_paths={prefix+name for prefix in ('A:\\','A:\\飞天音乐\\') for name in ('QQMusic.cfg','QQMusic.auth0','QQMusic.auth1')}
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
        self.install(files,0x24,0x80e20100,'remove')
        self.install(files,0x30,0x80e20120,'mkdir');self.put(0x80e20120,struct.pack('<3I',0x27bdffd8,0x03e00008,0))
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

    def read_memory(self, address, n):
        # A debugger observation must not execute another instruction slice.
        # The outer scheduler advances the MIPS CPU exactly once per turn.
        return self.get(address, n)
    def call(self, name, *args):
        """Invoke the actual linked MIPS leaf API while preserving suspended UI registers."""
        saved = self.u.context_save(); old_pc = self.pc
        stack = 0x81100000; sentinel = 0x80eff000
        self.u.reg_write(UC_MIPS_REG_SP, stack); self.u.reg_write(UC_MIPS_REG_RA, sentinel)
        for register, value in zip((UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3), args):
            self.u.reg_write(register, value)
        if len(args) > 4: self.put(stack+16, struct.pack('<'+'I'*(len(args)-4), *args[4:]))
        pc = self.symbols[name]
        try:
            for _ in range(50000):
                self.budget = 100000; self.u.emu_start(pc, sentinel); pc = self.u.reg_read(UC_MIPS_REG_PC)
                if pc == sentinel: return self.u.reg_read(UC_MIPS_REG_V0)
            raise TimeoutError('MIPS direct call did not return: '+name)
        finally:
            self.u.context_restore(saved); self.pc = old_pc
