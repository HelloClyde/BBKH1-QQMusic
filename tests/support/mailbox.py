"""Connect the model's validated in-memory mailbox to a synthetic protocol peer."""
from pathlib import Path
import hashlib,json,struct,secrets
from .http_peer import Backend,Parser,Server
ROOT=Path(__file__).resolve().parents[2]
class MailboxBridge:
    def __init__(self,client,metadata=ROOT/'dist/H1QQMusicDbg.build.json'):
        self.client=client
        self.metadata=json.loads(Path(metadata).read_text(encoding='utf-8'))
        if self.metadata.get('transport')!='h1debug-mailbox':raise ValueError('Expected debug-transport build')
        artifact=ROOT/self.metadata.get('artifact','dist/H1QQMusicDbg.bda')
        raw=artifact.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.metadata['sha256']:raise ValueError('BDA changed after build')
        payload=self.metadata['validation']['payload_offset']
        if client.read_memory(0x83c00020,256)!=raw[payload:payload+256]:raise ValueError('Loaded BDA entry differs from this build')
        self.layout=self.metadata['debug_mailbox'];self.address=self.layout['address']
        header=self.header()
        if header[:4] != [self.layout['magic'],1,self.layout['size'],self.layout['build_id']] or header[4]!=1:
            raise ValueError('Loaded BDA mailbox schema/build identity mismatch')
        self.backend=Backend();self.server=Server(self.backend);self.trace=[];self.url_sequence=header[15]
        self.session=(secrets.randbits(32) or 1) if self.layout.get('connection_tokens') else 1
        self.write_word(10,self.session)
    def header(self):return list(struct.unpack('<16I',self.client.read_memory(self.address,64)))
    def write_word(self,index,value):self.client.write_memory(self.address+index*4,struct.pack('<I',value))
    def service(self):
        header=self.header()
        if header[4]!=1:raise RuntimeError('Foreground BDA exited')
        if not header[5]:return header
        if not 16<=header[6]<=528 or header[7]:raise RuntimeError('Mailbox transaction bounds/ownership mismatch')
        parser=Parser();request=self.client.read_memory(self.address+self.layout['tx_offset'],header[6])
        frames=parser.feed(request)
        if len(frames)!=1 or parser.buffer or parser.bad_crc or parser.bad_headers:raise RuntimeError('Invalid H1NET request from MIPS model')
        reply=self.server.dispatch(frames[0])
        event=dict(opcode=frames[0][0],sequence=frames[0][1],request_bytes=len(request),reply_bytes=len(reply))
        if frames[0][0]==3:event['url']=frames[0][3][8:].decode('utf-8',errors='replace')
        self.trace.append(event)
        self.client.write_memory(self.address+self.layout['rx_offset'],reply)
        self.client.write_memory(self.address+8*4,struct.pack('<II',len(reply),0))
        self.write_word(5,0)
        self.write_word(7,1)  # Publish only after the entire frame and lengths are written.
        return header
