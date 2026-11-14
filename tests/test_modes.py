"""Linked MIPS queue/UI/PCM tests. Synthetic media/provider and firmware cursor.
No EOF/success flags are injected; transitions use real demux/decoder/ring drain.
"""
from pathlib import Path
from fractions import Fraction
import argparse, hashlib, json, math, struct, time
from support import music as q
from support.audio_injection import TimedModel
from support import http_peer as pc
ROOT = q.ROOT
OUT = ROOT / 'build/qqmusic/modes-0.1.12'
OUT.mkdir(parents=True, exist_ok=True)
CFG = 'A:\\QQMusic.cfg'
seconds = 1

def tone(path):
    c = q.av.open(str(path), 'w', format='ipod')
    s = c.add_stream('aac', rate=16000)
    s.layout = 'mono'
    s.bit_rate = 48000
    total = int(seconds * 16000)
    for start in range(0, total, 1024):
        n = min(1024, total - start)
        f = q.av.AudioFrame(format='s16', layout='mono', samples=n)
        f.sample_rate = 16000
        f.pts = start
        f.time_base = Fraction(1, 16000)
        f.planes[0].update(struct.pack('<%dh' % n, *[round(7000 * math.sin(2 * math.pi * 440 * (start + i) / 16000)) for i in range(n)]))
        for p in s.encode(f):
            c.mux(p)
    for p in s.encode(None):
        c.mux(p)
    c.close()

class Model(TimedModel):
    initial_files = {}

    def __init__(self):
        super().__init__()
        self.files = dict(self.initial_files)

class Harness(q.Harness):

    def key(self, *keys):
        self.until(lambda: not self.m.word('busy'))
        return super().key(*keys)

    def close(self):
        self.until(lambda: not self.m.word('busy'))
        self.m.allow_exit = True
        self.m.keys.extend([24, 24])
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            self.m.step()
            if self.bridge.header()[4] == 1:
                self.bridge.service()
            self.m.consume()
            if self.m.pc == self.m.stop:
                break
        self.m.allow_exit = True
        assert self.m.pc == self.m.stop and (not self.m.drawing) and (not self.m.allocations) and (not self.m.handles) and (not self.m.invalid)
        assert all((c['path'] in ('A:\\QQMusic.auth0', 'A:\\QQMusic.auth1', CFG) for c in self.m.file_calls))
        assert all((c['mode'] == 'rb' or (c['path'] == CFG and c['mode'] == 'wb') for c in self.m.file_calls))
        self.backend.close()
        self.audio.close()

def policy_checks(m):
    p = 2164916224

    def begin(n, current, mode):
        m.call('qm_queue_begin', p, n, current, mode, 12345)

    def move(action):
        return m.call('qm_queue_move', p, action)
    for n in range(1, 13):
        begin(n, 0, 0)
        assert move(-1) == 12
        assert [move(2) for _ in range(n)] == list(range(1, n)) + [12]
        begin(n, n - 1, 1)
        assert move(2) == 0 and move(-1) == n - 1
        begin(n, 0, 2)
        assert move(2) == 0 and move(1) == 1 % n and (move(-1) == 0)
        begin(n, 0, 3)
        first = [0] + [move(2) for _ in range(n - 1)]
        assert len(set(first)) == n
        last = first[-1]
        next_ = move(2)
        assert n == 1 or next_ != last
        assert move(-1) == last and move(1) == next_
        for _ in range(30):
            old = struct.unpack('<I', m.get(p + 4, 4))[0]
            new = move(2)
            assert new < n and (n == 1 or new != old)

def main():
    global seconds
    q.OUT = OUT
    q.Model = Model
    q.tone = tone
    fixture = q.Fixture()
    h = None
    checks = []
    fixture.tracks = [dict(fixture.tracks[0], songmid=f'{i + 1:014d}', songname='队列歌曲 %d' % i) for i in range(3)]
    report = dict(passed=False, physical_h1=False, physical_esp32=False, checks=checks)

    def passed(s):
        checks.append(s)
        print('PASS', s, flush=True)

    def current():
        return q.TRACK.unpack(m.get(m.symbols['qm_current'], q.TRACK.size))[0].split(b'\x00')[0].decode()

    def words(name):
        return struct.unpack('<16I', m.get(m.symbols[name], 64))
    try:
        h = Harness(fixture)
        m = h.m
        policy_checks(m)
        passed('linked queue policy: counts 1..12; order bounds, wrap, single/manual skip, shuffle bag and actual previous/forward history')
        exercise_modes(h, m, fixture, passed)
        h.close()
        h = None
        saved = dict(m.files)
        data = saved[CFG]
        assert len(data) == 16 and struct.unpack_from('<I', data, 8)[0] == 3
        Model.initial_files = saved
        h = Harness(fixture)
        m = h.m
        h.until(lambda: m.word('open_ok'))
        assert m.word('play_mode') == 3
        h.close()
        h = None
        Model.initial_files = {}
        passed('normal exit writes only owned 16-byte CRC config; fresh app restores mode and frees all resources')
        seconds = 0.4
        tone(OUT / 'tone.m4a')
        fixture.media = (OUT / 'tone.m4a').read_bytes()
        fixture.tracks[1]['pay'] = {'payplay': 1, 'paydownload': 0}
        h = Harness(fixture)
        m = h.m
        h.key(13, 25)
        h.until(lambda: m.play()['eof'] and m.word('queue_index') == 2 and m.word('end_handled'), timeout=180)
        assert len(h.audio.sessions) == 2
        h.close()
        h = None
        passed('automatic order skips anonymous member track without a vkey request or retry loop')
        seconds = 4
        tone(OUT / 'tone.m4a')
        fixture.media = (OUT / 'tone.m4a').read_bytes()
        fixture.tracks = fixture.tracks[:1]
        h = Harness(fixture)
        m = h.m
        h.key(13, 25)
        h.until(lambda: m.play()['ms'] >= 300)
        d = words('qm_buffer_diag')
        r = words('qm_aac_state')
        assert d[4] >= 49152 and d[5] >= 1 and (r[11] == 0)
        h.key(23)
        paused = m.play()['ms']
        assert not m.play()['playing']
        for _ in range(10):
            h.until(lambda: True)
        assert m.play()['ms'] == paused
        h.key(23)
        h.until(lambda: m.play()['ms'] > paused + 100)
        h.key(35)
        h.until(lambda: m.play()['eof'] or m.play()['error'])
        assert m.play()['eof'] and (not m.play()['error'])
        report['buffer_diag'] = list(words('qm_buffer_diag'))
        report['remote_diag'] = list(words('qm_aac_state'))
        h.close()
        h = None
        passed('>=0.75 s real decoded reserve before output, zero empty reads; pause/resume/near-end seek drain and clean exit')
        report['passed'] = True
    finally:
        if h:
            report['failure'] = dict(state=m.state(), play=m.play(), notice=m.notice(), pc=hex(m.pc), diag=list(words('qm_player_diag')), buffer=list(words('qm_buffer_diag')))
            m.screenshot('failure.png')
            h.backend.close()
            h.audio.close()
        fixture.close()
        Model.initial_files = {}
        report['sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), ROOT / 'build/qqmusic/H1QQMusicDbg.elf', ROOT / 'dist/H1QQMusicDbg.bda')}
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PASS', len(checks), 'new mode/buffering groups;', len(report.get('reused_checks', [])), 'reused; model only')

def exercise_modes(h, m, fixture, passed):

    def current():
        return q.TRACK.unpack(m.get(m.symbols['qm_current'], q.TRACK.size))[0].split(b'\x00')[0].decode()
    h.key(13, 25)
    h.key(24)
    h.until(lambda: len(h.audio.sessions) == 3 and m.play()['eof'], timeout=180)
    assert m.state()['view'] == 0 and m.word('queue_index') == 2 and (not m.play()['error'])
    for _ in range(20):
        h.until(lambda: True)
    assert len(h.audio.sessions) == 3
    expected = [bytes(p) for p in q.av.open(str(OUT / 'tone.m4a')).demux(audio=0) if p.size]
    assert all((s['frames'] == expected for s in h.audio.sessions))
    passed('three real AAC streams automatically advance in background; final order track stops once; exact packet sequence and short-tail drain')
    h.key(31, 20, 23)
    n = len(h.audio.sessions)
    h.until(lambda: len(h.audio.sessions) > n)
    assert m.word('queue_index') == 0 and m.word('play_mode') == 1
    h.key(20)
    n = len(h.audio.sessions)
    index = m.word('queue_index')
    h.until(lambda: len(h.audio.sessions) > n)
    assert m.word('queue_index') == index and m.word('play_mode') == 2
    h.key(36)
    assert m.word('queue_index') == (index + 1) % 3
    passed('list loop wraps at real EOF; single loop reopens same track; manual Next still changes song')
    before = m.word('inputs')
    m.events.extend([(11, 0, 390, 16), (8, 0, 390, 16)])
    h.until(lambda: m.completed_inputs > before)
    assert m.word('play_mode') == 3
    old = current()
    h.key(36)
    assert current() != old
    new = current()
    h.key(21)
    assert current() == old
    h.key(36)
    assert current() == new
    m.screenshot('01-shuffle-player.png')
    passed('touch chip and B cycle modes; shuffle Next avoids same track and Previous/Next retrace actual history')
if __name__ == '__main__':
    main()
