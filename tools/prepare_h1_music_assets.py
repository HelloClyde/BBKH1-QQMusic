"""Pack the generated QQ-derived H1 icon; no creative image edits."""
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
def prepare():
    assets=ROOT/'h1-qqmusic/assets'
    with Image.open(assets/'icon-h1-centered-v4.png') as opened:
        image=opened.convert('RGBA')
        image.resize((360,360),Image.Resampling.LANCZOS).save(assets/'icon.png')
        parts=['/* Generated from the QQ-derived imagegen master; see assets/icon-h1-centered-design.json. */',
               'typedef struct {unsigned size;const uint32_t *rgba;} qm_bitmap;']
        for size in (22,29,50,68):
            logo=image.resize((size,size),Image.Resampling.LANCZOS)
            words=[(a<<24)|(r<<16)|(g<<8)|b for r,g,b,a in logo.getdata()]
            rows=[','.join(f'0x{v:08x}u' for v in words[i:i+8]) for i in range(0,len(words),8)]
            parts.extend([f'static const uint32_t qm_logo_{size}_rgba[{size}*{size}]={{',
                          ',\n'.join(rows),'};',
                          f'static const qm_bitmap qm_logo_{size}={{{size},qm_logo_{size}_rgba}};'])
    (ROOT/'h1-qqmusic/ui_assets.h').write_text('\n'.join(parts)+'\n')
    print('Packed QQ Music logos directly from master at 22, 29, 50 and 68 pixels')
if __name__=='__main__':prepare()
