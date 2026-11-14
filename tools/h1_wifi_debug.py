"""Relay H1NET/1 through a verified foreground BDA mailbox while H1Debug owns USB."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import time
import secrets
from h1_debug import Client
from h1_wifi_pc import Backend,Parser,Server,valid_url

ROOT=Path(__file__).resolve().parents[1]

class DebugBridge:
    def __init__(self,client,metadata=ROOT/'dist/H1WiFiDbg.build.json'):
        self.client=client
        self.metadata=json.loads(Path(metadata).read_text(encoding='utf-8'))
        if self.metadata.get('transport')!='h1debug-mailbox':raise ValueError('Expected debug-transport build')
        artifact=ROOT/self.metadata.get('artifact','dist/H1WiFiDbg.bda')
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
    def set_url(self,url):
        if not valid_url(url):raise ValueError('Invalid test URL')
        raw=url.encode('utf-8');self.client.write_memory(self.address+self.layout['url_offset'],raw)
        self.client.write_memory(self.address+self.layout['url_length_offset'],struct.pack('<I',len(raw)))
        self.url_sequence=(self.url_sequence+1)&0xffffffff or 1
        self.write_word(15,self.url_sequence)
        time.sleep(.15)  # Foreground applies the URL before it consumes the next key event.

    def service(self):
        header=self.header()
        if header[4]!=1:raise RuntimeError('Foreground BDA exited')
        if not header[5]:return header
        if not 16<=header[6]<=528 or header[7]:raise RuntimeError('Mailbox transaction bounds/ownership mismatch')
        parser=Parser();request=self.client.read_memory(self.address+self.layout['tx_offset'],header[6])
        frames=parser.feed(request)
        if len(frames)!=1 or parser.buffer or parser.bad_crc or parser.bad_headers:raise RuntimeError('Invalid H1NET request from physical H1')
        reply=self.server.dispatch(frames[0])
        event=dict(opcode=frames[0][0],sequence=frames[0][1],request_bytes=len(request),reply_bytes=len(reply))
        if frames[0][0]==3:event['url']=frames[0][3][8:].decode('utf-8',errors='replace')
        self.trace.append(event)
        self.client.write_memory(self.address+self.layout['rx_offset'],reply)
        self.client.write_memory(self.address+8*4,struct.pack('<II',len(reply),0))
        self.write_word(5,0)
        self.write_word(7,1)  # Publish only after the entire frame and lengths are written.
        return header

    def result(self):
        raw=self.client.read_memory(self.address,196);header=list(struct.unpack_from('<16I',raw))
        words=struct.unpack_from('<8I',raw,64)
        info=dict(zip(('job','state','http_status','content_length','received','delivered','buffered','error'),words))
        error=header[13] if header[13]<0x80000000 else header[13]-0x100000000
        return dict(operation=header[11],completed=header[12],return_code=error,success=bool(header[14]),info=info,
                    path=raw[96:128].split(b'\0')[0].decode('ascii'),preview=raw[128:196].split(b'\0')[0].decode('utf-8',errors='replace'))

    def run_request(self,url,*,save=False,cancel=False,timeout=90):
        self.set_url(url);before=self.header()[11];start=time.monotonic();sent_cancel=False
        self.client.press(['D' if save else 'ENTER'],ticks=2)
        while time.monotonic()-start<timeout:
            header=self.service()
            if cancel and not sent_cancel and header[11]!=before and len(self.trace) and self.trace[-1]['opcode']==4:
                self.client.press(['ESCAPE'],ticks=2);sent_cancel=True
            if header[11]!=before and header[12]==header[11]:
                result=self.result();result['elapsed_seconds']=time.monotonic()-start;result['cancel_key_sent']=sent_cancel
                return result
            time.sleep(.005)
        raise TimeoutError('H1 request did not finish; outcome unknown, do not replay the key')

    def close(self):
        self.backend.close()
        if not self.client._broken:
            self.write_word(10,0)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--port')
    ap.add_argument('--metadata',type=Path,default=ROOT/'dist/H1WiFiDbg.build.json')
    args=ap.parse_args()
    with Client(args.port) as client:
        bridge=DebugBridge(client,args.metadata)
        print('Physical H1Debug bridge ready. On H1: Enter to GET, D to save. Ctrl+C stops the bridge.')
        try:
            while True:bridge.service();time.sleep(.005)
        except KeyboardInterrupt:pass
        finally:bridge.close()

if __name__=='__main__':main()
