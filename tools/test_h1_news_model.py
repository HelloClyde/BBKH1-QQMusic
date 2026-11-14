"""Run linked H1 News MIPS code with real HTTP and the unchanged PC Backend.

Only H1 firmware GUI/file/time/USB boundaries are modeled. The application,
RSS/HTML core, H1NET client, target heap/musl and PNG/JPEG decoder run as MIPS.
This is not physical H1 or ESP32 evidence. Full source articles stay in build/.
"""
from pathlib import Path
import argparse
import hashlib
import http.server
import io
import json
import struct
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone

from elftools.elf.elffile import ELFFile
from PIL import Image
from unicorn import (Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN,
                     UC_HOOK_BLOCK, UC_HOOK_CODE, UC_HOOK_MEM_INVALID)
from unicorn.mips_const import (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2,
                                UC_MIPS_REG_A3, UC_MIPS_REG_SP, UC_MIPS_REG_RA,
                                UC_MIPS_REG_PC, UC_MIPS_REG_V0)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'build/h1-news/model'
sys.path.insert(0, str(ROOT/'tests'))
from h1_netsurf import Model as Base
from h1_wifi_debug import DebugBridge

STATE_NAMES = ('magic', 'schema', 'phase', 'busy', 'view', 'requested_source',
               'loaded_source', 'count', 'selected', 'scroll', 'refresh_count',
               'requests', 'received', 'http', 'result', 'generation',
               'image_count', 'decoded_images', 'failed_images', 'presents',
               'connected', 'active_jobs', 'inputs', 'panic')
ITEM_FIELDS = (('title', 256), ('url', 401), ('published', 80), ('source', 96),
               ('summary', 513), ('body', 12289))
ITEM_SIZE = 15252
LONG_BODY = '\n'.join(f'{i:02d} 新闻长文滚动测试：中文正文、真实网络和图片同时可读。' for i in range(1, 49))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Fixture:
    """Threaded socket server; gates hold real HTTP bodies, never MIPS results."""
    def __init__(self):
        self.requests = []
        self.mode = 'normal'
        self.gates = {name: threading.Event() for name in ('feed', 'old-image', 'parallel')}
        self.entered = {name: threading.Event() for name in self.gates}
        self.http_lock = threading.Lock(); self.parallel_active = 0; self.parallel_peak = 0
        self.closed = False
        self.images = {}
        self.pillow = {}
        for name, fmt, color in (('fixture.png', 'PNG', None),
                                 ('fixture.jpg', 'JPEG', None),
                                 ('old.png', 'PNG', (235, 35, 35)),
                                 ('new.png', 'PNG', (25, 65, 235)),
                                 ('fourth.png', 'PNG', (30, 195, 190))):
            image = Image.new('RGB', (96, 64), color or (0, 0, 0))
            if color is None:
                for y in range(image.height):
                    for x in range(image.width):
                        image.putpixel((x, y), ((238, 28, 48), (36, 202, 64),
                                                (24, 76, 232), (245, 218, 31))[(x>=48)+2*(y>=32)])
            buffer = io.BytesIO()
            image.save(buffer, format=fmt, **({'quality': 95, 'subsampling': 0} if fmt == 'JPEG' else {}))
            self.images[name] = buffer.getvalue()
            self.pillow[name] = Image.open(io.BytesIO(self.images[name])).convert('RGB')
        rgba = Image.new('RGBA', (96, 64), (220, 40, 80, 128))
        buffer = io.BytesIO(); rgba.save(buffer, format='PNG')
        self.images['alpha.png'] = buffer.getvalue()
        white = Image.new('RGBA', rgba.size, (255, 255, 255, 255)); white.alpha_composite(rgba)
        self.pillow['alpha.png'] = white.convert('RGB')
        buffer = io.BytesIO(); Image.new('RGB', (4097, 1), (20, 30, 40)).save(buffer, format='PNG')
        self.images['oversize.png'] = buffer.getvalue()
        self.images['broken.png'] = b'\x89PNG\r\n\x1a\nnot-a-valid-png'
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                record = {'path': path, 'received_at': utc_now(), 'mode': owner.mode}
                owner.requests.append(record)
                if path == '/feed.xml':
                    if owner.mode == 'http-error':
                        self.respond(b'fixture unavailable', 'text/plain', 503)
                        return
                    raw = owner.feed()
                    if owner.mode == 'large-feed':
                        raw=raw.replace(b'</channel>',b'<!--'+b'bounded timing fixture '*5000+b'--></channel>')
                    if owner.mode == 'truncated':
                        self.send_response(200); self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
                        self.send_header('Content-Length', str(len(raw)+31)); self.send_header('Connection', 'close')
                        self.end_headers(); self.wfile.write(raw[:len(raw)//2]); self.wfile.flush()
                        self.close_connection = True; return
                    if owner.mode == 'hold':
                        self.send_response(200); self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
                        self.send_header('Content-Length', str(len(raw))); self.end_headers()
                        self.wfile.write(raw[:47]); self.wfile.flush()
                        owner.entered['feed'].set(); owner.gates['feed'].wait(30)
                        try: self.wfile.write(raw[47:]); self.wfile.flush()
                        except (ConnectionError, OSError): record['peer_closed'] = True
                        return
                    self.respond(raw, 'application/rss+xml; charset=utf-8'); return
                name = path.rsplit('/', 1)[-1]
                if name in owner.images:
                    raw = owner.images[name]
                    if path.startswith('/parallel/'):
                        with owner.http_lock:
                            owner.parallel_active += 1
                            owner.parallel_peak = max(owner.parallel_peak, owner.parallel_active)
                            if owner.parallel_active == 4: owner.gates['parallel'].set()
                        try:
                            if not owner.gates['parallel'].wait(15):
                                self.respond(b'four simultaneous HTTP requests not observed', 'text/plain', 504); return
                            self.respond(raw, 'image/jpeg' if name.endswith('.jpg') else 'image/png'); return
                        finally:
                            with owner.http_lock: owner.parallel_active -= 1
                    if path == '/slow/old.png':
                        self.send_response(200); self.send_header('Content-Type', 'image/png')
                        self.send_header('Content-Length', str(len(raw))); self.end_headers()
                        self.wfile.write(raw[:16]); self.wfile.flush()
                        owner.entered['old-image'].set(); owner.gates['old-image'].wait(30)
                        try: self.wfile.write(raw[16:]); self.wfile.flush()
                        except (ConnectionError, OSError): record['peer_closed'] = True
                        return
                    self.respond(raw, 'image/jpeg' if name.endswith('.jpg') else 'image/png'); return
                self.respond(b'<html><body>fixture article is already complete in RSS</body></html>', 'text/html; charset=utf-8')

            def respond(self, raw, content_type, status=200):
                self.send_response(status); self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(raw))); self.send_header('Connection', 'close')
                self.end_headers(); self.close_connection = True
                try:
                    # Deliberately split XML, UTF-8 and image bytes across actual writes.
                    for start in range(0, len(raw), 317):
                        self.wfile.write(raw[start:start+317]); self.wfile.flush()
                except (ConnectionError, OSError): record = None

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.endpoint = self.origin+'/feed.xml'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def feed(self):
        items = (
            ('中文新闻标题：PNG 与 JPEG', LONG_BODY,
             ('/parallel/fixture.png', '/parallel/fixture.jpg', '/parallel/alpha.png', '/parallel/fourth.png')),
            ('旧文章：等待图片时仍能操作', '旧文章正文。'+LONG_BODY, ('/slow/old.png',)),
            ('新文章：蓝色图片不能串图', '新文章正文。'+LONG_BODY, ('/new.png',)),
            ('坏图与过大图：文字仍可阅读', '坏图不会破坏这段中文正文。'+LONG_BODY, ('/broken.png', '/oversize.png')),
        )
        if self.mode=='gestures': items=items*2
        body = []
        for i, (title, text, images) in enumerate(items):
            html = '<p>'+text.replace('\n', '</p><p>')+'</p>'+''.join('<img src="'+self.origin+x+'">' for x in images)
            body.append(f'<item><title>{title}</title><link>{self.origin}/article/{i}</link>'
                        '<pubDate>Thu, 12 Nov 2026 19:08:07 +0800</pubDate>'
                        '<source>模型新闻源</source><content:encoded><![CDATA['+html+']]></content:encoded></item>')
        return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
                '<title>真实本地 HTTP 新闻源</title><lastBuildDate>Thu, 12 Nov 2026 19:08:07 +0800</lastBuildDate>'
                +''.join(body)+'</channel></rss>').encode()

    def save(self):
        directory = OUT/'fixtures'; directory.mkdir(parents=True, exist_ok=True)
        for name, raw in self.images.items(): (directory/name).write_bytes(raw)
        (directory/'feed.xml').write_bytes(self.feed())

    def close(self):
        self.closed = True
        for gate in self.gates.values(): gate.set()
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)


class Model(Base):
    def __init__(self, elf_path):
        # Only the firmware boundaries actually used by this product are hooked.
        self.u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        self.u.mem_map(0, 64*1024*1024)
        self.start = self.timer_origin = time.monotonic()
        self.timer_frozen = 0; self.timer_running = False
        self.touch_events=[]
        self.keys = []; self.fb = 0x81200000; self.stop = 0x83bff000
        self.allow_exit = False; self.drawing = False; self.frames = 0
        self.allocations = {}; self.blocks = [(0x81400000, 16*1024*1024)]
        self.minimum_stack = 0xffffffff; self.files = {}; self.handles = {}
        self.next_handle = 1; self.file_calls = []; self.invalid = None; self.budget = 0
        self.native_buffer_calls = 0; self.blit_calls = 0
        self.http_opens = []; self.feed_captures = []; self.image_captures = []
        with elf_path.open('rb') as stream:
            elf = ELFFile(stream)
            for segment in elf.iter_segments():
                if segment['p_type'] == 'PT_LOAD': self.put(segment['p_vaddr'], segment.data())
            self.symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        def boundary(u, address, size, data):
            if self.budget <= 0: u.emu_stop(); return
            self.budget -= max(size//4, 1)
        self.u.hook_add(UC_HOOK_BLOCK, boundary)
        table = 0x80010000; self.put(0x83c00004, struct.pack('<I', table))
        entries = ((0x714, 'start'), (0x718, 'stop'), (0x71c, 'time'),
                   (0x84c, 'open'), (0x850, 'close'), (0x8f4, 'buffer'),
                   (0x750, 'keys'), (0x6d8, 'raw-time'), (0x400, 'blit'), (0x70, 'present'))
        for i, (offset, kind) in enumerate(entries): self.install(table, offset, 0x80e00000+i*16, kind)
        coordinate=0x80e00300
        self.put(table+0x6c0,struct.pack('<I',coordinate))
        self.put(coordinate,struct.pack('<17I',0x27bdffa8,0xafbf0050,0xafb60048,0xafb7004c,0x00a0b821,0x0080b021,
            0x3c088109,0x95090000,0xa4890000,0x95090002,0xa4a90000,
            0x8fb60048,0x8fb7004c,0x8fbf0050,0x27bd0058,0x03e00008,0))
        memory = 0x80020000; self.put(0x83c00010, struct.pack('<I', memory))
        for i, (offset, kind) in enumerate(((8, 'alloc'), (12, 'free'))): self.install(memory, offset, 0x80e10000+i*16, kind)
        files = 0x80030000; self.put(0x83c00008, struct.pack('<I', files))
        for i, kind in enumerate(('fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell')):
            self.install(files, i*4, 0x80e20000+i*16, kind)
        for symbol, kind in (('fw_matches', 'fw'), ('fw_delay', 'delay')):
            if symbol in self.symbols:
                self.u.hook_add(UC_HOOK_CODE, self.hook(kind), begin=self.symbols[symbol], end=self.symbols[symbol])
        def observed_open(u, address, size, data):
            self.http_opens.append({'slot': u.reg_read(UC_MIPS_REG_A0),
                                    'url': self.cstring(u.reg_read(UC_MIPS_REG_A1)),
                                    'maximum': u.reg_read(UC_MIPS_REG_A2), 'started_at': utc_now()})
        def observed_feed(u, address, size, data):
            self.feed_captures.append(self.get(u.reg_read(UC_MIPS_REG_A0), u.reg_read(UC_MIPS_REG_A1)))
        def observed_image(u, address, size, data):
            if self.native_buffer_calls:
                self.image_captures.append(self.get(u.reg_read(UC_MIPS_REG_A0), u.reg_read(UC_MIPS_REG_A1)))
        for symbol, observer in (('news_net_start', observed_open), ('news_feed_parse', observed_feed),
                                 ('news_image_decode', observed_image)):
            self.u.hook_add(UC_HOOK_CODE, observer, begin=self.symbols[symbol], end=self.symbols[symbol])
        self.rpc_clock_driver=None
        def rpc_clock_boundary(u,address,size,unused):
            if self.rpc_clock_driver:self.rpc_clock_driver()
        address=self.symbols['h1net_rpc_begin']
        self.u.hook_add(UC_HOOK_CODE,rpc_clock_boundary,begin=address,end=address)
        def invalid(u, access, address, size, value, data):
            self.invalid = [access, hex(address), size, hex(value)]; return False
        self.u.hook_add(UC_HOOK_MEM_INVALID, invalid)
        self.pc = self.symbols['h1_bda_main']
        self.u.reg_write(UC_MIPS_REG_SP, 0x83b00000); self.u.reg_write(UC_MIPS_REG_RA, self.stop)

    def cstring(self, address, encoding='utf-8', limit=4096):
        return self.get(address, limit).split(b'\0', 1)[0].decode(encoding, 'strict')

    def hook(self, kind):
        if kind=='keys':
            normal=super().hook(kind)
            def keys(u,address,size,unused):
                if not self.touch_events:return normal(u,address,size,unused)
                code,x,y=self.touch_events.pop(0)
                self.put(0x81090000,struct.pack('<2H',x,y))
                self.put(u.reg_read(UC_MIPS_REG_A0),struct.pack('<i',code))
                self.put(u.reg_read(UC_MIPS_REG_A1),struct.pack('<i',0))
                u.reg_write(UC_MIPS_REG_PC,u.reg_read(UC_MIPS_REG_RA))
            return keys
        if kind not in ('fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'buffer', 'blit', 'present'):
            return super().hook(kind)
        def run(u, address, size, unused):
            args = [u.reg_read(reg) for reg in (UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2, UC_MIPS_REG_A3)]
            value = 0
            if kind == 'buffer':
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
                if path in self.files or 'w' in mode:
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

    def state(self):
        values = struct.unpack('<24I', self.get(self.symbols['news_state'], 96))
        result = dict(zip(STATE_NAMES, values))
        if result['result'] >= 0x80000000: result['result'] -= 0x100000000
        return result

    def item(self, detail=True, index=0):
        address = self.symbols['news_detail' if detail else 'news_list']+(0 if detail else index*ITEM_SIZE)
        item = {}; offset = 0
        for name, n in ITEM_FIELDS:
            item[name] = self.get(address+offset, n).split(b'\0', 1)[0].decode('utf-8', 'replace'); offset += n
        item['images'] = [self.get(address+offset+i*401, 401).split(b'\0', 1)[0].decode() for i in range(4)]
        item['image_count'], item['body_truncated'], item['body_is_summary'] = struct.unpack('<3I', self.get(address+15240, 12))
        return item

    def image(self, index):
        def entry(name): return struct.unpack('<I', self.get(self.symbols[name]+index*4, 4))[0]
        pointer, width, height = (entry('news_image_'+name) for name in ('pixels', 'width', 'height'))
        return {'pointer': pointer, 'width': width, 'height': height, 'result': entry('news_image_result'),
                'rgb565': self.get(pointer, width*height*2) if pointer and width*height else b''}

    def screenshot(self, name):
        Image.frombytes('RGB', (480, 272), self.get(self.fb, 480*272*4), 'raw', 'BGRX').save(OUT/name)

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


def rgb565_samples(raw, width, height):
    points = ((8, 8), (width-9, 8), (8, height-9), (width-9, height-9))
    return [(x, y, struct.unpack_from('<H', raw, (y*width+x)*2)[0]) for x, y in points]


def verify_pixels(raw, width, height, reference, jpeg=False):
    assert (width, height) == reference.size, ((width, height), reference.size)
    samples = []
    for x, y, value in rgb565_samples(raw, width, height):
        expected = reference.getpixel((x, y))
        expected565 = ((expected[0]>>3)<<11)|((expected[1]>>2)<<5)|(expected[2]>>3)
        if jpeg:
            actual = ((value>>11)*255//31, ((value>>5)&63)*255//63, (value&31)*255//31)
            assert max(abs(a-b) for a, b in zip(actual, expected)) <= 18, (actual, expected)
        else: assert value == expected565, (hex(value), hex(expected565))
        samples.append({'x': x, 'y': y, 'actual_rgb565': value, 'expected_rgb565': expected565})
    return samples


def decoder_checks(model, fixture, report):
    results = []
    for name in ('fixture.png', 'fixture.jpg', 'alpha.png', 'broken.png', 'oversize.png'):
        raw = fixture.images[name]; model.put(0x81000000, raw); model.put(0x81080000, bytes(12))
        before = model.word('h1ns_heap_live')
        result = model.call('news_image_decode', 0x81000000, len(raw), 0x81080000,
                            0x81080004, 0x81080008, 448, 180)
        pointer, width, height = struct.unpack('<3I', model.get(0x81080000, 12))
        row = {'name': name, 'result': result, 'width': width, 'height': height}
        if name in fixture.pillow:
            assert result == 0 and pointer, row
            row['samples'] = verify_pixels(model.get(pointer, width*height*2), width, height,
                                           fixture.pillow[name], name.endswith('.jpg'))
            model.call('free', pointer)
        else: assert result != 0 and not pointer, row
        assert model.word('h1ns_heap_live') == before, 'decoder leaked '+name
        results.append(row)
    report['decoder_samples'] = results
    report['checks'].append('real MIPS PNG/JPEG decode matches Pillow RGB565 samples; PNG alpha blends white; corrupt/oversize images reject without heap leaks')


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, default=ROOT/'dist/H1NewsDbg.build.json')
    parser.add_argument('--live', action='store_true', help='Run official IT Home RSS and image via real MIPS and unchanged PC Backend')
    parser.add_argument('--gestures',action='store_true')
    parser.add_argument('--timing-only', action='store_true', help='Validate corrected clock cases and reuse exact-ELF successful pre-timing assertions')
    args = parser.parse_args(); args.metadata = args.metadata.resolve()
    if args.timing_only and args.live: parser.error('--timing-only does not use --live')
    if args.live: OUT = ROOT/'build/h1-news/model/live'
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = json.loads(args.metadata.read_text(encoding='utf-8'))
    elf = ROOT/metadata.get('elf', 'build/h1-news/H1NewsDbg.elf')
    fixture = Fixture();
    if args.gestures: fixture.mode="gestures"
    fixture.save(); model = Model(elf); bridge = None
    report = {'passed': False, 'physical_h1': False, 'physical_esp32': False,
              'method': 'real linked MIPS UI/core/network/heap/musl/image; modeled firmware GUI/file/time/USB; unchanged PC Backend with actual HTTP sockets',
              'command': 'python tools/test_h1_news_model.py --metadata '+args.metadata.relative_to(ROOT).as_posix()+(' --live' if args.live else ''),
              'bda_sha256': metadata['sha256'], 'elf_sha256': hashlib.sha256(elf.read_bytes()).hexdigest(),
              'started_at': utc_now(), 'checks': [], 'snapshots': [],
              'test_inputs': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                              ('tools/test_h1_news_model.py', 'tools/h1_wifi_debug.py', 'tools/h1_wifi_pc.py')}}


    if args.timing_only:
        previous_path=ROOT/'build/h1-news/hardware-20261113-otg-speed/failed-model-rpc-clock.json'
        previous=json.loads(previous_path.read_text(encoding='utf-8'))
        assert previous['bda_sha256']==metadata['sha256'] and previous['elf_sha256']==report['elf_sha256']
        prior_script=previous_path.with_suffix('.py')
        assert hashlib.sha256(prior_script.read_bytes()).hexdigest()==previous['test_inputs']['tools/test_h1_news_model.py']
        for path,digest in previous['test_inputs'].items():
            if path!='tools/test_h1_news_model.py':assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
        assert previous['checks'][-1].startswith('continuous actual HTTP body progress')
        report['reused_checks']=previous['checks'][:-1]
        report['reused_partial_evidence']=dict(path=previous_path.relative_to(ROOT).as_posix(),
            sha256=hashlib.sha256(previous_path.read_bytes()).hexdigest(),
            reason='Successful pre-timing assertions on the exact same BDA/ELF; the prior failure was the new clock driver crossing an in-flight RPC budget.')

    def wait(predicate, seconds=40):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if bridge: bridge.service()
            model.step()
            if model.state()['panic']: raise RuntimeError('MIPS panic '+str(model.state()['panic']))
            if predicate(): return model.state()
        raise TimeoutError(json.dumps({'state': model.state(), 'status': model.string('news_status', 192), 'pc': hex(model.pc)}, ensure_ascii=False))

    def key(code, predicate):
        model.keys.append(code); return wait(predicate)

    def snapshot(name):
        before = model.state()['presents']; wait(lambda: model.state()['presents'] >= before+2)
        model.screenshot(name+'.png')
        report['snapshots'].append({'name': name, 'state': model.state(), 'status': model.string('news_status', 192),
                                    'item_title': model.item()['title'] if model.state()['view'] else model.item(False)['title']})

    def idle():
        return wait(lambda: not model.state()['busy'])

    def refresh(mode='normal', successful=True):
        fixture.mode = mode; before = model.state()['refresh_count']; inputs = model.state()['inputs']
        key(4, lambda: model.state()['inputs'] > inputs)
        state = idle()
        assert state['refresh_count'] == before+(1 if successful else 0), state
        return state

    def select(index):
        while model.state()['selected'] < index:
            old = model.state()['selected']; key(27, lambda: model.state()['selected'] > old)
        while model.state()['selected'] > index:
            old = model.state()['selected']; key(37, lambda: model.state()['selected'] < old)

    def timed_refresh(mode, on_progress, successful):
        # Advance only the modeled firmware clock at a NEW async RPC boundary.
        # No existing RPC is aged artificially; its 4s budget remains meaningful.
        fixture.mode=mode;before=model.state()['refresh_count'];inputs=model.state()['inputs']
        mark=model.word('news_net_received');initial_mark=mark;advanced=0;boundaries=0
        started=model.call('h1ns_time_ms')
        def advance_clock():
            nonlocal mark,advanced,boundaries
            boundaries+=1
            current=model.word('news_net_received')
            if (on_progress and current!=mark) or (not on_progress and current!=initial_mark):
                # The stalled case starts its clock steps only AFTER genuine
                # body bytes arrive, and reaches 45s before the real socket's
                # independent 5s read timeout. No RPC is already in flight here.
                step=3.0 if on_progress else 10.0
                model.timer_origin-=step;advanced+=step;mark=current
        model.rpc_clock_driver=advance_clock
        try:
            key(4,lambda:model.state()['inputs']>inputs)
            state=wait(lambda:not model.state()['busy'],90)
        finally:model.rpc_clock_driver=None
        timing=dict(advanced_seconds=advanced,elapsed_clock_seconds=((model.call('h1ns_time_ms')-started)&0xffffffff)/1000,rpc_boundaries=boundaries,timer_running=model.timer_running)
        assert state['refresh_count']==before+int(successful),state
        if not successful:assert state['result']==-2 and state['phase']==6,(state,timing)
        assert boundaries, 'clock hook must observe new RPC entries'
        return timing

    def open_item(index):
        select(index); key(25, lambda: model.state()['view'] == 1)

    def down(count):
        for _ in range(count):
            before = model.state()['inputs']; key(27, lambda: model.state()['inputs'] > before)

    def back():
        key(24, lambda: model.state()['view'] == 0); idle()

    def exit_app():
        nonlocal bridge
        if model.state()['view']: back()
        idle(); report['bridge_trace'] = bridge.trace; bridge.close(); bridge = None
        model.allow_exit = True; key(24, lambda: model.pc == model.stop)
        assert not model.allocations and not model.handles and not model.drawing
        assert model.word('h1ns_heap_live') == 0 and model.word('h1ns_heap_reserved') == 0
        assert model.word('h1ns_heap_abandoned') == 0 and model.word('h1ns_heap_integrity') == 0
        assert model.native_buffer_calls > 0 and model.blit_calls == 0
        report['checks'].append('exit returns from the MIPS entry with no heap abandonment, valid TLSF integrity, no SDK allocations/file handles/drawing context; native 0x8f4 used and no SDK blit')

    try:
        wait(lambda: model.state()['magic'] == 0x3153574e and model.state()['presents'])
        assert model.state()['schema'] == 1
        # The BDA entry clears BSS. Run direct library checks after its first
        # frame so their target-heap arena is not erased by startup itself.
        if not args.live and not args.timing_only and not args.gestures: decoder_checks(model, fixture, report)
        bridge = DebugBridge(model, args.metadata)
        # Publish URL before stepping the new connection: loopback tests must
        # not accidentally begin the application's default official-source GET.
        bridge.set_url('https://www.ithome.com/rss/' if args.live else fixture.endpoint)
        wait(lambda: bool(model.state()['connected']) and model.state()['refresh_count'] == 1 and not model.state()['busy'], 90)
        state = model.state()
        assert state['count'] and state['http'] == 200 and state['received'] > 0 and not state['result'], state
        snapshot('01-online-list')

        if args.gestures:
            assert state['count']>4
            model.touch_events.extend([(11,60,190),(12,60,100),(8,65535,65535)])
            wait(lambda:model.word('list_offset')==90 and not model.touch_events)
            assert not model.state()['view']
            model.touch_events.extend([(11,60,155),(8,60,155)])
            wait(lambda:model.state()['view']==1)
            assert model.state()['selected']==4
            idle()
            model.touch_events.append((11,70,190))
            wait(lambda:not model.touch_events)
            model.put(0x81090000,struct.pack('<2H',70,70))
            wait(lambda:model.state()['scroll']==120)
            model.touch_events.extend([(12,70,150),(8,65535,65535)])
            wait(lambda:model.state()['scroll']==40 and not model.touch_events)
            report['checks'].append('list moves 90 pixels on event 12, invalid release suppresses tap, tap selects scrolled row 4, article tracks held finger and reverses 80 pixels')
        elif args.live:
            first = model.item(False)
            candidates = [(i, model.item(False, i)) for i in range(state['count'])]
            index, item = next((i, item) for i, item in candidates if item['image_count'])
            report['live_source'] = {'url': 'https://www.ithome.com/rss/', 'fetched_at': utc_now(),
                                     'latest_published': first['published'], 'latest_title': first['title'],
                                     'count': state['count'], 'received': state['received']}
            report['checks'].append('unchanged PC Backend performs an official HTTPS IT Home RSS GET consumed and parsed by the real MIPS application')
            open_item(index); idle()
            state = model.state()
            assert state['image_count'] > 0 and state['decoded_images'] > 0, state
            current = model.item()
            report['live_article'] = {k: current[k] for k in ('title', 'url', 'published', 'source', 'images', 'image_count')}
            report['live_article'].update(body_bytes=len(current['body'].encode()),
                                           body_sha256=hashlib.sha256(current['body'].encode()).hexdigest())
            snapshot('02-live-title-time')
            down(2); snapshot('03-live-official-image')
            down(6); snapshot('04-live-long-body')
            assert model.state()['scroll'] > 0 and current['body']
            report['checks'].append('official article body and official thumbnail decode/display locally on MIPS, with working detail scrolling')
        else:
            assert state['count'] == 4 and model.item(False)['title'].startswith('中文新闻标题')
            assert model.item(False)['published'] == 'Thu, 12 Nov 2026 19:08:07 +0800'
            if not args.timing_only:
                report['checks'].append('real local fragmented UTF-8 RSS GET publishes four Chinese titles, source dates and nonzero delivered bytes')
                open_item(0); idle()
                state = model.state()
                assert state['decoded_images'] == 4 and state['image_count'] == 4 and not state['failed_images'], state
                assert fixture.parallel_peak == 4, fixture.parallel_peak
                assert model.word('news_net_peak_active') == 4
                for i, name in enumerate(('fixture.png', 'fixture.jpg', 'alpha.png', 'fourth.png')):
                    image = model.image(i)
                    assert image['result'] == 2
                    samples = verify_pixels(image['rgb565'], image['width'], image['height'], fixture.pillow[name], name.endswith('.jpg'))
                    report.setdefault('ui_image_samples', []).append({'index': i, 'name': name, 'samples': samples})
                assert '48 新闻长文滚动测试' in model.item()['body']
                snapshot('02-detail-title-time')
                down(2); snapshot('03-png-image')
                inputs = model.state()['inputs']; key(29, lambda: model.state()['inputs'] > inputs)
                assert model.word('news_image_selected') == 1
                down(2); snapshot('04-jpeg-image')
                down(6); snapshot('05-long-body')
                assert model.state()['scroll'] > 108
                report['checks'].append('four actual simultaneous HTTP workers complete PNG/JPEG/alpha images; actual UI RGB565 buffers match Pillow samples; I switches image and Down scrolls long Chinese text')
                back()

                before = model.state()['received']; state = refresh()
                assert state['received'] > before and state['refresh_count'] == 2
                old_first = model.item(False)
                report['checks'].append('successful refresh increments the success count and records newly delivered network bytes')
                for mode, http in (('http-error', 503), ('truncated', 200)):
                    state = refresh(mode, False)
                    assert state['phase'] == 6 and state['http'] == http and state['result'] != 0
                    assert model.item(False) == old_first and state['count'] == 4
                    snapshot('06-'+mode)
                    report['checks'].append(mode+' refresh preserves the complete old list and exposes an explicit failure status')

                fixture.mode = 'hold'; before = model.state()['received']; inputs = model.state()['inputs']
                key(4, lambda: model.state()['inputs'] > inputs)
                wait(lambda: fixture.entered['feed'].is_set() and model.state()['busy'] and model.state()['received'] > before)
                key(24, lambda: not model.state()['busy'])
                fixture.gates['feed'].set()
                assert model.state()['refresh_count'] == 2 and model.item(False) == old_first
                assert '取消' in model.string('news_status', 192)
                snapshot('07-cancelled-refresh')
                report['checks'].append('Escape cancels a genuinely partial HTTP refresh, preserves the old list and displays cancellation')
                refresh()

                open_item(1)
                wait(lambda: fixture.entered['old-image'].is_set() and model.state()['busy'])
                assert model.image(0)['result'] == 1
                down(7); assert model.state()['scroll'] > 0 and model.state()['busy']
                assert '旧文章正文' in model.item()['body']
                snapshot('08-stalled-image-readable-body')
                report['checks'].append('while an image HTTP body is deliberately stalled, MIPS still handles scroll keys and renders long article text')
                back(); open_item(2); idle()
                assert model.item()['title'].startswith('新文章') and model.state()['decoded_images'] == 1
                new_image = model.image(0); new_bytes = new_image['rgb565']
                verify_pixels(new_bytes, new_image['width'], new_image['height'], fixture.pillow['new.png'])
                fixture.gates['old-image'].set()
                presents = model.state()['presents']; wait(lambda: model.state()['presents'] >= presents+4)
                assert model.image(0)['rgb565'] == new_bytes and model.item()['title'].startswith('新文章')
                down(2); snapshot('09-new-article-no-stale-image')
                report['checks'].append('after cancelling the stalled old article, late old HTTP bytes cannot replace the new article image or text')
                back(); open_item(3); idle()
                assert model.state()['failed_images'] == 2 and not model.state()['decoded_images']
                assert '坏图不会破坏这段中文正文' in model.item()['body']
                snapshot('10-bad-images-status'); down(7); snapshot('11-bad-images-readable-body')
                report['checks'].append('corrupt and over-dimension images fail independently while the Chinese article remains readable and scrollable')
                back()

                bridge.write_word(10, 0); wait(lambda: not model.state()['connected'])
                state = refresh('normal', False)
                assert state['phase'] == 6 and model.item(False) == old_first
                assert 'USB未连接' in model.string('news_status', 192)
                snapshot('12-disconnected-preserved-list')
                bridge.write_word(10, bridge.session); wait(lambda: bool(model.state()['connected']))
                refresh()
                report['checks'].append('USB session loss preserves the list with an explicit disconnected status, and restoring the connection allows another real HTTP refresh')

                # Legitimate provider restart, with the device-side USB epoch unchanged.
                trace_start=len(bridge.trace)
                bridge.server=type(bridge.server)(bridge.backend)
                refresh()
                assert [x['opcode'] for x in bridge.trace[trace_start:trace_start+4]]==[2,1,10,2]
                report['checks'].append('ESP protocol-session restart with unchanged USB epoch automatically re-handshakes and refreshes without restarting the application')

            timing=timed_refresh('normal',True,True)
            assert timing['advanced_seconds']>45,timing
            report['checks'].append('continuous actual HTTP body progress beyond 45 modeled seconds completes; no blanket 45-second request cancellation')
            report['progress_timing']=timing
            fixture.gates['feed'].clear();fixture.entered['feed'].clear()
            try:
                timing=timed_refresh('hold',False,False)
                assert timing['elapsed_clock_seconds']>=45,timing
                report['stall_timing']=timing
            finally:fixture.gates['feed'].set()
            report['checks'].append('stalled real HTTP body still times out after 45 seconds without byte progress, preserving the old list')
            timing=timed_refresh('large-feed',True,False)
            assert timing['elapsed_clock_seconds']>=180,timing
            report['total_bound_timing']=timing
            report['checks'].append('continuously progressing large HTTP body still obeys the independent 180-second total bound')

        exit_app(); report['passed'] = True
    except BaseException as error:
        report.update(error=str(error), state=model.state(), status=model.string('news_status', 192),
                      pc=hex(model.u.reg_read(UC_MIPS_REG_PC)), sp=hex(model.u.reg_read(UC_MIPS_REG_SP)),
                      ra=hex(model.u.reg_read(UC_MIPS_REG_RA)), invalid=model.invalid)
        raise
    finally:
        if bridge:
            report['bridge_trace'] = bridge.trace; bridge.close()
        fixture.close(); model.screenshot('last.png')
        captures = OUT/'captures'; captures.mkdir(parents=True, exist_ok=True)
        for i, raw in enumerate(model.feed_captures): (captures/f'feed-{i+1:02d}.xml').write_bytes(raw)
        for i, raw in enumerate(model.image_captures): (captures/f'image-{i+1:02d}.bin').write_bytes(raw)
        report.update(requests=fixture.requests, observed_http_opens=model.http_opens,
                      capture_files=[{'path': p.relative_to(ROOT).as_posix(), 'bytes': p.stat().st_size,
                                      'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in captures.iterdir() if p.is_file()],
                      server_parallel_http_peak=fixture.parallel_peak,
                      file_calls=model.file_calls, open_handles=len(model.handles),
                      live_sdk_allocations=len(model.allocations), drawing_open=model.drawing,
                      native_buffer_calls=model.native_buffer_calls, blit_calls=model.blit_calls,
                      ended_at=utc_now())
        for name in ('h1ns_heap_live', 'h1ns_heap_peak', 'h1ns_heap_reserved', 'h1ns_heap_abandoned', 'h1ns_heap_integrity'):
            if name in model.symbols: report[name] = model.word(name)
        (OUT/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('PASS linked MIPS News '+('official-live' if args.live else 'local-integration')+':', len(report['checks']), 'executed checks;',len(report.get('reused_checks',[])), 'reused exact-ELF checks; not physical H1/ESP32 evidence')


if __name__ == '__main__':
    main()
