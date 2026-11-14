"""Reject accidental inclusion of sibling applications or hardware debug tooling."""
from pathlib import Path
import ast,re
ROOT=Path(__file__).resolve().parents[1]
def main():
    forbidden=('h1-news','h1-bilibili','h1-debug','h1-netsurf','h1-wifi','h1-qqmusic')
    assert all(not (ROOT/name).exists() for name in forbidden),'Sibling app directory in repository'
    assert not (ROOT/'tools/h1_debug.py').exists(),'Hardware debugger CLI is not a music dependency'
    bad_imports={'h1_debug','h1_wifi_debug','test_h1_news_model','test_h1_wifi_settings_model','h1_netsurf'}
    for base in ('tools','tests'):
        for p in (ROOT/base).rglob('*.py'):
            for n in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
                modules=[a.name for a in n.names] if isinstance(n,ast.Import) else [n.module or ''] if isinstance(n,ast.ImportFrom) else []
                assert not bad_imports.intersection(modules),str(p.relative_to(ROOT))
    for name in ('src/main.c','src/platform/images.c','src/platform/aac_remote.c','tests/support/firmware.py','tests/support/mailbox.py','assets/fonts/OFL-1.1.txt'):
        assert (ROOT/name).is_file(),name
    image=(ROOT/'src/platform/images.c').read_text(encoding='utf-8')
    assert 'news_image_url' not in image and 'ithome' not in image,'Provider-specific image URL policy leaked into decoder'
    aac=(ROOT/'src/platform/aac_remote.c').read_text(encoding='utf-8')
    assert '#define bili_' not in aac and '../h1-' not in aac,'AAC client must be standalone'
    readme=(ROOT/'README.md').read_text(encoding='utf-8')
    assert all('## '+s in readme for s in ('快速开始','截图','依赖','感谢'))
    print('PASS repository scope: music app, SDK dependencies and pure model support only')
if __name__=='__main__':main()
