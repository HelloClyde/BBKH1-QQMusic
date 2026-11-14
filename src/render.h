/* QQ Music palette and canvas bindings; rendering is implemented by the SDK. */
#include "h1_draw.h"
#include "h1_font16.h"
static uint16_t pixels[480*272];
static h1_canvas canvas={pixels,480,272,480,0,272,&h1_font16_cjk};
#define clip_top canvas.clip_top
#define clip_bottom canvas.clip_bottom
#define qm_utf8_next h1_utf8_next
#define qm_glyph_advance(cp) h1_draw_advance(canvas.font,cp)
#define rect(...) h1_draw_rect(&canvas,__VA_ARGS__)
#define glyph(...) h1_draw_glyph(&canvas,__VA_ARGS__)
#define text(...) h1_draw_text(&canvas,__VA_ARGS__)
#define draw_text(...) h1_draw_text_at(&canvas,__VA_ARGS__)
#define text_ellipsis(...) h1_draw_ellipsis(&canvas,__VA_ARGS__)
#define ui_round(...) h1_draw_round(&canvas,__VA_ARGS__)
#define ui_dot(...) h1_draw_dot(&canvas,__VA_ARGS__)
#define ui_line(...) h1_draw_line(&canvas,__VA_ARGS__)
#define ui_width(s) h1_draw_width(canvas.font,s)
#define UI_RGB(v) ((uint16_t)((((v)>>19)&31)<<11|(((v)>>10)&63)<<5|(((v)>>3)&31)))
#define UI_BG UI_RGB(0xf2f2f7)
#define UI_INK UI_RGB(0x1c1c1e)
#define UI_SUB UI_RGB(0x63636b)
#define UI_LINE UI_RGB(0xe5e5ea)
#define UI_BLUE UI_RGB(0x007aff)
#define UI_TINT UI_RGB(0xe9f2ff)
#define UI_GREEN UI_RGB(0x248a3d)
#define UI_RED UI_RGB(0xc93434)
#define UI_WHITE ((uint16_t)0xffff)
static void ui_chevron(int x,int y,int back,uint16_t color)
{
    int end=back?x-4:x+4;ui_line(x,y,end,y+4,color);ui_line(end,y+4,x,y+8,color);
    ui_line(x+1,y,end+1,y+4,color);ui_line(end+1,y+4,x+1,y+8,color);
}



static void ui_center(const char *s,int x,int y,int width,uint16_t color)
{int n=ui_width(s);text(s,x+(n<width?(width-n)/2:0),y,x+width,color);}
