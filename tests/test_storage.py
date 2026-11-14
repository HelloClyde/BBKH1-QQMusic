"""Run real linked MIPS storage migration using synthetic files only."""
import hashlib,json,struct,zlib
import test_accounts as a
ROOT=a.ROOT
OUT=ROOT/'build/qqmusic/storage-0.1.13';OUT.mkdir(parents=True,exist_ok=True)
NEW=a.PATHS;OLD=a.LEGACY
CFG='A:\\飞天音乐\\QQMusic.cfg';LEGACY_CFG='A:\\QQMusic.cfg'
def auth(text,gen):
    body=text.encode();head=struct.pack('<5I',0x31414d51,1,gen,len(body),zlib.crc32(body))
    return head+struct.pack('<I',zlib.crc32(head))+body
def cfg(mode):
    head=struct.pack('<3I',0x31434d51,1,mode);return head+struct.pack('<I',zlib.crc32(head))
def main():
    a.q.OUT=OUT
    fixture=a.Fixture();h=None;checks=[]
    text=json.dumps(dict(str_musicid='12345',musickey='Q_Qsynthetic-music-key',loginType=2))
    def boot(files,fail=False):
        a.Model.fail_initial=fail
        try:return a.Harness(fixture,files)
        finally:a.Model.fail_initial=False
    def passed(s):checks.append(s);print('PASS',s,flush=True)
    report=dict(passed=False,physical_h1=False,physical_esp32=False,checks=checks)
    try:
        h=boot({OLD[0]:auth(text,8),OLD[1]:auth(text,7)})
        assert h.m.mkdir_calls==['A:\\飞天音乐']
        assert any(p in h.m.files and len(h.m.files[p])>24 for p in NEW)
        assert not any(p in h.m.files for p in OLD)
        h.until(lambda:h.m.account()['logged']==1)
        h.close();h=None;passed('GBK directory creation and legacy newest login migrate with real write/readback before cleanup')
        h=boot({OLD[0]:auth(text,8),OLD[1]:auth('',9)})
        assert not h.m.account()['logged'] and any(h.m.files.get(p)==auth('',10) for p in NEW)
        h.close();h=None;passed('newest legacy logout tombstone migrates and does not resurrect older login')
        h=boot({NEW[0]:auth('',1),OLD[1]:auth(text,99)})
        assert not h.m.account()['logged'] and h.m.files[NEW[0]]==auth('',1)
        assert not any(c['path'] in OLD for c in h.m.file_calls)
        h.close();h=None;passed('valid new-directory state wins over stale legacy data regardless of generation')
        h=boot({OLD[0]:auth(text,8)},True)
        assert h.m.files[OLD[0]]==auth(text,8)
        assert not any(len(h.m.files.get(p,b''))>=24 for p in NEW)
        h.until(lambda:h.m.account()['logged']==1 or h.m.account()['state']==6)
        h.close();h=None;passed('failed migration write preserves original credential and never creates a valid new generation')
        h=boot({OLD[0]:auth('',4),OLD[1]:auth(text,5)[:-1],NEW[1]:b'corrupt'})
        assert not h.m.account()['logged'] and any(h.m.files.get(p)==auth('',5) for p in NEW)
        h.close();h=None;passed('truncated/corrupt slots are rejected; last validated logout generation is migrated')
        h=boot({LEGACY_CFG:cfg(3)})
        assert h.m.word('play_mode')==3 and CFG not in h.m.files
        h.close();assert h.m.files[CFG]==cfg(3) and LEGACY_CFG not in h.m.files;h=None
        passed('playback mode migrates on normal exit only and old cfg is removed after exact readback')
        h=boot({CFG:cfg(1),LEGACY_CFG:cfg(3)})
        assert h.m.word('play_mode')==1
        h.close();h=None;passed('valid new-directory playback mode is preferred')
        report['passed']=True
    finally:
        if h:h.backend.close();h.audio.close()
        fixture.close();report['bda_sha256']=hashlib.sha256((ROOT/'dist/H1QQMusicDbg.bda').read_bytes()).hexdigest()
        (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
