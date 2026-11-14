/* Native 480x272 shapes: bounded integer geometry, RGB565, no runtime assets. */
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
static void ui_round(int x,int y,int w,int h,int radius,uint16_t color)
{
    for(int row=0;row<h;row++){
        int d=row<radius?radius-1-row:row>=h-radius?row-h+radius:0,inset=0;
        if(d)while(inset<radius&&(radius-inset)*(radius-inset)+d*d>radius*radius)inset++;
        rect(x+inset,y+row,w-2*inset,1,color);
    }
}

static void ui_dot(int x,int y,int radius,uint16_t color)
{
    for(int dy=-radius;dy<=radius;dy++)for(int dx=-radius;dx<=radius;dx++)
        if(dx*dx+dy*dy<=radius*radius)rect(x+dx,y+dy,1,1,color);
}

static void ui_line(int x,int y,int x2,int y2,uint16_t color)
{
    int dx=x2>x?x2-x:x-x2,sx=x<x2?1:-1,dy=y2>y?y-y2:y2-y,sy=y<y2?1:-1,err=dx+dy;
    for(;;){rect(x,y,1,1,color);if(x==x2&&y==y2)break;int e=2*err;if(e>=dy){err+=dy;x+=sx;}if(e<=dx){err+=dx;y+=sy;}}
}

static void ui_chevron(int x,int y,int back,uint16_t color)
{
    int end=back?x-4:x+4;ui_line(x,y,end,y+4,color);ui_line(end,y+4,x,y+8,color);
    ui_line(x+1,y,end+1,y+4,color);ui_line(end+1,y+4,x+1,y+8,color);
}

static int ui_width(const char *s)
{int width=0;while(*s){unsigned cp=(unsigned)qm_utf8_next(&s);width+=(int)qm_glyph_advance(cp);}return width;}

static void ui_center(const char *s,int x,int y,int width,uint16_t color)
{int n=ui_width(s);text(s,x+(n<width?(width-n)/2:0),y,x+width,color);}
