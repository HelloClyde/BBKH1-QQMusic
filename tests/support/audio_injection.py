"""Controlled DAC underruns and AUDIO_PUSH backpressure, no result injection."""
import struct
from unicorn.mips_const import UC_MIPS_REG_V0,UC_MIPS_REG_PC,UC_MIPS_REG_RA
from . import music as q, http_peer as pc

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
