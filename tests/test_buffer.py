"""Targeted actual MIPS PCM reserve/backpressure/recovery test; no hardware claim."""
import argparse, hashlib, json, struct
from pathlib import Path
from support import music as q
import test_modes as mode
from support.audio_injection import Audio, underrun
from support import http_peer as pc
ROOT = q.ROOT
OUT = ROOT / 'build/qqmusic/buffer-0.1.12'
OUT.mkdir(parents=True, exist_ok=True)

def main():
    q.OUT = OUT
    q.Model = mode.Model
    q.tone = mode.tone
    mode.seconds = 8
    fixture = q.Fixture()
    fixture.tracks = fixture.tracks[:1]
    h = None
    checks = []
    report = dict(passed=False, physical_h1=False, physical_esp32=False, checks=checks)

    def passed(s):
        checks.append(s)
        print('PASS', s, flush=True)
    try:
        h = mode.Harness(fixture)
        m = h.m
        h.audio.close()
        audio = Audio()
        h.audio = audio
        h.bridge.server = pc.Server(h.backend, audio)

        def words(name):
            return struct.unpack('<16I', m.get(m.symbols[name], 64))
        h.key(13, 25)
        h.until(lambda: m.play()['ms'] >= 300 and m.word('queued') < 7000)
        assert words('qm_buffer_diag')[4] >= 49152 and words('qm_buffer_diag')[5] == 1
        assert words('qm_aac_state')[11] == 0
        passed('real AAC decode accumulates >=49152 PCM bytes before native output; no empty AUDIO_READ polling')
        before = m.play()['ms']
        audio.busy = 3
        audio.inject = lambda: underrun(m)
        h.until(lambda: words('qm_player_diag')[12] >= 1 and m.play()['ms'] > before + 100 or m.play()['error'])
        assert not m.play()['error'] and (not words('qm_player_diag')[2])
        assert words('qm_aac_state')[14] == 0
        passed('AAC PUSH BUSY callback survives scripted native underflow; refill resumes retired media clock without decoder reset')
        for count in (2, 3):
            h.until(lambda: m.word('queued') < 7000 and m.hw_running)
            before = m.play()['ms']
            underrun(m)
            h.until(lambda: words('qm_player_diag')[12] >= count and m.play()['ms'] > before + 100 or m.play()['error'])
            assert not m.play()['error'] and (not words('qm_player_diag')[2])
        assert words('qm_aac_state')[14] == 0 and words('qm_buffer_diag')[6] == 3
        passed('three forced underflows preserve HTTP/MOV/AAC, rebuild reserve and continue media progress; strict clock remains enabled')
        audio.fail_reads = True
        h.until(lambda: m.play()['error'])
        assert words('qm_player_diag')[2:4] == (1, -105 & 4294967295)
        report['buffer_diag'] = list(words('qm_buffer_diag'))
        report['player_diag'] = list(words('qm_player_diag'))
        report['remote_diag'] = list(words('qm_aac_state'))
        h.close()
        h = None
        passed('real error reply stops playback with retained reason; normal exit closes jobs/ring and releases heap/handles')
        report['passed'] = True
    finally:
        if h:
            report['failure'] = dict(state=m.state(), play=m.play(), notice=m.notice(), pc=hex(m.pc), buffer=list(words('qm_buffer_diag')), player=list(words('qm_player_diag')))
            m.screenshot('failure.png')
            h.backend.close()
            h.audio.close()
        fixture.close()
        report['sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (q.ROOT / 'dist/H1QQMusicDbg.bda', q.ROOT / 'build/qqmusic/H1QQMusicDbg.elf', Path(__file__))}
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('PASS', len(checks), 'PCM buffer groups; model only')
if __name__ == '__main__':
    main()
