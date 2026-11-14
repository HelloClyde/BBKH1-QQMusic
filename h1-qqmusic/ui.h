/* QQ-inspired native 480x272 layout. All playback/network work stays outside this file. */
#include "ui_assets.h"
#define QM_ACCENT UI_RGB(0x24d58d)
#define QM_MUTED UI_RGB(0xc0d0d2)
static unsigned qm_ui_dark;
static uint16_t qm_mix(uint16_t a,uint16_t b,unsigned alpha)
{
    unsigned r=(((a>>11)*alpha+(b>>11)*(255-alpha))+127)/255;
    unsigned g=((((a>>5)&63)*alpha+((b>>5)&63)*(255-alpha))+127)/255;
    unsigned blue=(((a&31)*alpha+(b&31)*(255-alpha))+127)/255;
    return (uint16_t)((r<<11)|(g<<5)|blue);
}
static uint16_t qm_rgb(unsigned r,unsigned g,unsigned b)
{return (uint16_t)(((r>>3)<<11)|((g>>2)<<5)|(b>>3));}
static void qm_logo(int x,int y,const qm_bitmap *image)
{
    unsigned size=image->size;
    for(unsigned row=0;row<size;row++)for(unsigned col=0;col<size;col++){
        uint32_t rgba=image->rgba[row*size+col];unsigned a=rgba>>24;
        if(a){uint16_t color=qm_rgb((rgba>>16)&255,(rgba>>8)&255,rgba&255);unsigned pos=(unsigned)(y+(int)row)*480+(unsigned)x+col;pixels[pos]=qm_mix(color,pixels[pos],a);}
    }
}
/* Titles, metadata and controls all use unscaled 16px pixel glyphs. */
static void qm_title(const char *s,int x,int y,int right,uint16_t color)
{text_ellipsis(s,x,y,right,color);}
static void qm_small(const char *s,int x,int y,int right,uint16_t color)
{text_ellipsis(s,x,y,right,color);}
static void qm_triangle(int x,int y,unsigned size,int direction,uint16_t color)
{
    for(unsigned row=0;row<size;row++){int half=(int)(row<=size/2?row:size-1-row);int width=(half*2+1)*3/4+1;
        if(direction>0)rect(x,y+(int)row,width,1,color);else rect(x-width,y+(int)row,width,1,color);}
}
static void qm_skip(int x,int y,int direction,uint16_t color)
{qm_triangle(x-(direction>0?6:-6),y-8,17,direction,color);rect(x+(direction>0?8:-10),y-8,2,17,color);}
static void qm_speaker(int x,int y,int plus,uint16_t color)
{
    rect(x,y+5,4,7,color);for(int i=0;i<6;i++)rect(x+4+i,y+5-i,1,7+2*i,color);
    ui_line(x+13,y+7,x+20,y+7,color);if(plus)ui_line(x+17,y+3,x+17,y+11,color);
}
static void qm_search_icon(int x,int y,uint16_t color)
{ui_dot(x,y,6,color);ui_dot(x,y,4,qm_ui_dark?UI_RGB(0x14292e):UI_RGB(0xe8f5ed));ui_line(x+5,y+5,x+10,y+10,color);ui_line(x+6,y+5,x+11,y+10,color);}
static void qm_disc(int x,int y,unsigned size)
{ui_dot(x+(int)size/2,y+(int)size/2,(int)size/2,UI_RGB(0x1d3437));ui_dot(x+(int)size/2,y+(int)size/2,(int)size/2-5,UI_RGB(0x10252c));qm_logo(x+(int)size/2-25,y+(int)size/2-25,&qm_logo_50);}
static void qm_background(void)
{
    unsigned ar=80,ag=130,ab=120,count=0;
    if(cover){ar=ag=ab=0;for(unsigned y=0;y<cover_h;y+=8)for(unsigned x=0;x<cover_w;x+=8){unsigned c=cover[y*cover_w+x];ar+=(c>>11)*255/31;ag+=((c>>5)&63)*255/63;ab+=(c&31)*255/31;count++;}if(count){ar/=count;ag/=count;ab/=count;}}
    for(unsigned y=0;y<272;y++){
        unsigned r=8+ar*(300-y)/2400,g=16+ag*(300-y)/1800,b=20+ab*(300-y)/1800;
        for(unsigned x=0;x<480;x++){unsigned d=((x&1)^((y&1)<<1));pixels[y*480+x]=qm_rgb(r+d,g+d,b+d);}
    }
}
static int qm_in_round(unsigned x,unsigned y,unsigned side,unsigned radius)
{int dx=x<radius?(int)(radius-1-x):x>=side-radius?(int)(x-side+radius):0,dy=y<radius?(int)(radius-1-y):y>=side-radius?(int)(y-side+radius):0;return dx*dx+dy*dy<=(int)(radius*radius);}
static void qm_artwork(void)
{
    ui_round(22,49,148,148,10,UI_RGB(0x071216));ui_round(20,46,148,148,10,UI_RGB(0x0b1d23));
    if(!cover){qm_disc(20,44,148);return;}
    for(unsigned y=0;y<148;y++)for(unsigned x=0;x<148;x++)if(qm_in_round(x,y,148,8))
        pixels[(44+y)*480+20+x]=cover[(y*cover_h/148)*cover_w+x*cover_w/148];
}
static void qm_sidebar(unsigned tab)
{
    rect(0,0,480,272,UI_RGB(0xf8faf9));rect(0,0,137,272,UI_RGB(0xe8f5ed));rect(136,0,1,272,UI_RGB(0xdcebe2));
    qm_logo(12,12,&qm_logo_29);text("QQ音乐",48,19,133,UI_RGB(0x176c4d));
    static const char *labels[]={"首页","热歌榜","搜索","正在播放","账号"};
    for(unsigned i=0;i<5;i++){
        int y=56+(int)i*30;uint16_t ink=tab==i?UI_WHITE:UI_RGB(0x47745e);
        ui_round(10,y,117,28,7,tab==i?UI_RGB(0x19b879):UI_RGB(0xe8f5ed));
        if(i==0){ui_line(19,y+13,27,y+6,ink);ui_line(27,y+6,35,y+13,ink);rect(22,y+13,10,9,ink);rect(26,y+17,3,5,tab==i?UI_RGB(0x19b879):UI_RGB(0xe8f5ed));}
        else if(i==1){ui_line(22,y+11,22,y+22,ink);ui_line(27,y+7,27,y+22,ink);ui_line(32,y+13,32,y+22,ink);}
        else if(i==2)qm_search_icon(26,y+13,ink);
        else if(i==3){if(qm_play.playing){rect(22,y+8,3,13,ink);rect(29,y+8,3,13,ink);}else qm_triangle(23,y+7,15,1,ink);}
        else {ui_dot(26,y+10,4,ink);ui_round(19,y+16,15,8,4,ink);}
        text(labels[i],43,y+6,124,ink);
    }
    static const char *connection[]={"等待设备","连接设备中","Wi-Fi未连接","已联网","设备未响应"};
    qm_small(connection[qm_connection_status],17,209,132,UI_RGB(0x47745e));
    ui_round(10,238,117,26,7,UI_RGB(0xddeee4));qm_small("Esc 退出",26,243,121,UI_RGB(0x47745e));
}
static void qm_draw_list(void)
{
    qm_sidebar(search_mode?2:1);
    qm_title(search_mode?"搜索结果":"热歌榜",156,15,316,UI_INK);
    char line[120];snprintf(line,sizeof line,"第%u页",page);qm_small(line,306,21,372,UI_SUB);
    ui_round(378,12,38,30,8,UI_WHITE);ui_chevron(398,22,1,UI_BLUE);ui_round(430,12,38,30,8,UI_WHITE);ui_chevron(446,22,0,UI_BLUE);
    text_ellipsis(search_mode?query:"发现此刻值得听的好音乐",157,45,470,UI_SUB);
    if(!qm_songs.count){qm_logo(280,84,&qm_logo_68);ui_center("想听什么，搜一下",150,174,323,UI_INK);qm_small("热歌榜 / 中文搜索",220,202,466,UI_SUB);}
    unsigned first=first_row();
    clip_top=67;clip_bottom=235;
    for(unsigned row=0;row<5&&first+row<qm_songs.count;row++){
        unsigned i=first+row;qm_track *s=qm_songs.tracks+i;int y=69+(int)i*42-list_offset;int chosen=i==selected;
        if(chosen)ui_round(147,y-2,325,42,7,UI_RGB(0xe1f4e9));else if(row)rect(185,y-3,280,1,UI_RGB(0xeaf0ec));
        snprintf(line,sizeof line,"%02u",(page-1)*QM_TRACKS+i+1);text(line,156,y+2,184,i<3?UI_RGB(0xc49a25):UI_RGB(0x8da096));
        text_ellipsis(s->title,188,y,436,chosen?UI_RGB(0x118559):UI_INK);qm_small(s->artist,189,y+20,382,UI_SUB);
        if(s->paid&QM_RIGHTS_PLAYABLE)qm_small("可播放",410,y+20,470,UI_BLUE);
        else if((s->paid&QM_RIGHTS_MASK)==QM_RIGHTS_MEMBER)qm_small("会员曲",410,y+20,470,UI_RGB(0xa88431));
        else if((s->paid&QM_RIGHTS_MASK)==QM_RIGHTS_UNKNOWN)qm_small("待验证",410,y+20,470,UI_SUB);
        else {snprintf(line,sizeof line,"%u:%02u",s->seconds/60,s->seconds%60);qm_small(line,429,y+20,470,UI_SUB);}
        if(chosen){ui_dot(455,y+7,10,UI_RGB(0x19b879));qm_triangle(452,y+1,12,1,UI_WHITE);}
    }
    clip_top=0;clip_bottom=272;
    ui_dot(152,259,2,UI_BLUE);qm_small(qm_notice,162,249,473,UI_SUB);
}
static void qm_draw_home(void)
{
    qm_sidebar(0);text("首页",156,15,470,UI_INK);text("音乐，随时相伴",156,45,470,UI_SUB);
    text("听点什么？",157,84,470,UI_INK);
    ui_round(155,120,146,44,9,UI_RGB(0xe1f4e9));text("热歌榜 H",184,135,297,UI_BLUE);
    ui_round(315,120,153,44,9,UI_RGB(0xe1f4e9));text("搜索音乐 S",346,135,466,UI_BLUE);
    if(qm_current.mid[0]){
        ui_round(155,183,313,58,9,UI_WHITE);qm_logo(165,197,&qm_logo_29);
        text_ellipsis(qm_current.title,204,190,442,UI_INK);qm_small(qm_play.playing?"正在播放，点击返回":"继续收听",205,214,442,UI_SUB);ui_chevron(453,208,0,UI_BLUE);
    }else qm_small("从热歌榜发现，或搜索喜欢的歌",156,198,470,UI_SUB);
    qm_small(qm_notice,156,251,474,UI_SUB);
}
static void qm_draw_account(void)
{
    qm_sidebar(4);text("账号",156,15,325,UI_INK);
    qm_small(qm_account.logged?qm_account.nickname:"登录后使用账号的播放授权",156,43,470,UI_SUB);
    ui_round(150,60,190,190,10,UI_WHITE);
    if(qm_account_qr&&(qm_account.state==QM_AUTH_SCAN||qm_account.state==QM_AUTH_CONFIRM)){
        int x=153+(184-(int)qm_account_qr_width)/2,y=63+(184-(int)qm_account_qr_height)/2;
        for(unsigned row=0;row<qm_account_qr_height;row++)memcpy(pixels+(y+(int)row)*480+x,qm_account_qr+row*qm_account_qr_width,qm_account_qr_width*2);
    }else {
        qm_logo(220,103,&qm_logo_50);
        ui_center(qm_account.logged?"已登录":qm_account.state==QM_AUTH_FETCHING?"获取二维码中…":qm_account.state==QM_AUTH_RESTORE?"恢复登录中…":"选择右侧扫码登录",154,174,182,UI_INK);
    }
    ui_round(350,72,119,36,8,UI_RGB(0xe4f6ec));text("QQ扫码 Q",367,82,468,UI_BLUE);
    ui_round(350,117,119,36,8,UI_RGB(0xe4f6ec));text("微信扫码 W",359,127,468,UI_BLUE);
    ui_round(350,162,119,36,8,UI_WHITE);text("刷新码 R",368,172,468,UI_SUB);
    if(qm_account.logged){ui_round(350,207,119,36,8,UI_WHITE);text("退出登录 L",359,217,468,UI_SUB);}
    else {qm_small(qm_account.state==QM_AUTH_CONFIRM?"手机上确认":qm_account.state==QM_AUTH_EXPIRED?"二维码过期":qm_account.state==QM_AUTH_ERROR?"请重试":"手机扫一扫",354,216,470,UI_SUB);}
    if(qm_account.message[0])qm_small(qm_account.message,154,251,474,UI_SUB);
}
static void qm_draw_player(void)
{
    qm_background();ui_chevron(19,12,1,QM_MUTED);text("列表",29,9,78,QM_MUTED);
    ui_center(busy?"正在加载":qm_play.error?(qm_play.ready?"播放中断":"加载失败"):qm_player_buffering()?"正在缓冲":qm_play.playing?"正在播放":qm_play.eof?"播放结束":qm_play.ready?"已暂停":"尚未播放",177,9,127,QM_MUTED);
    ui_round(337,3,137,28,8,UI_RGB(0x294248));text(qm_queue_label(play_mode),347,9,417,QM_ACCENT);qm_small("B",451,9,470,QM_MUTED);
    qm_artwork();qm_title(qm_current.title[0]?qm_current.title:"正在准备音乐",195,46,467,UI_WHITE);text_ellipsis(qm_current.artist,196,77,467,QM_MUTED);
    if(qm_play.error||qm_cancelled){text_ellipsis(qm_notice,196,116,467,UI_RGB(0xf1b69b));}
    else if(qm_words.count){unsigned at=qm_lyric_at(&qm_words,qm_play.ms),start=at==UINT32_MAX?0:at?at-1:0;
        for(unsigned row=0;row<3&&start+row<qm_words.count;row++){unsigned i=start+row;text_ellipsis(qm_words.lines[i].text,196,113+(int)row*29,467,i==at?QM_ACCENT:QM_MUTED);}
    }else {text("暂无歌词",196,130,467,QM_MUTED);qm_small("让音乐陪伴此刻",197,158,468,QM_MUTED);}
    char line[64];snprintf(line,sizeof line,"%u:%02u",qm_play.ms/60000,qm_play.ms/1000%60);qm_small(line,21,217,90,QM_MUTED);
    snprintf(line,sizeof line,"%u:%02u",qm_play.duration/60000,qm_play.duration/1000%60);qm_small(line,420,217,477,QM_MUTED);
    ui_round(20,209,440,4,2,UI_RGB(0x3c5358));unsigned progress=qm_play.duration?(unsigned)((uint64_t)qm_play.ms*440/qm_play.duration):0;if(progress>440)progress=440;
    if(progress)ui_round(20,209,(int)progress,4,2,QM_ACCENT);ui_dot(20+(int)progress,211,3,UI_WHITE);
    ui_line(20,244,39,244,QM_MUTED);ui_line(20,250,39,250,QM_MUTED);ui_line(20,256,34,256,QM_MUTED);
    qm_skip(174,251,-1,UI_WHITE);ui_dot(240,251,19,QM_ACCENT);
    if(qm_play.playing&&!qm_play.error){ui_round(234,244,4,15,1,UI_RGB(0x102d27));ui_round(243,244,4,15,1,UI_RGB(0x102d27));}
    else qm_triangle(236,242,18,1,UI_RGB(0x102d27));
    qm_skip(306,251,1,UI_WHITE);qm_speaker(390,243,0,QM_MUTED);qm_speaker(441,243,1,QM_MUTED);
    snprintf(line,sizeof line,"%u",volume);qm_small(line,412,233,443,QM_MUTED);
}
void qm_paint(void)
{
    qm_ui_dark=view==1;if(view==1)qm_draw_player();else if(view==2)qm_draw_account();else if(view==QM_VIEW_HOME)qm_draw_home();else qm_draw_list();
    typedef volatile uint32_t *(*fn)(uint16_t *,void *);uint16_t info[6]={0};volatile uint32_t *out=((fn)h1_runtime_entry(h1_runtime_table(H1_RUNTIME_GUI_TABLE_SLOT),0x8f4))(info,NULL);
    if(out&&info[1]==480&&info[2]==272&&info[3]==1920&&info[5]==32){for(unsigned i=0;i<480*272;i++){unsigned c=pixels[i];out[i]=((c&0xf800)<<8)|((c&0x7e0)<<5)|((c&31)<<3);}presents++;}
    last_paint=qm_time();ui_dirty=0;publish();
}
static int touch_key(int x,int y)
{
    if(x<0||x>=480||y<0||y>=272)return 0;
    if(x<137&&view!=QM_VIEW_PLAYER){
        if(y>=238)return H1_KEY_ESCAPE;
        if(y>=56&&y<204){unsigned tab=(unsigned)(y-56)/30;static const int keys[]={QM_KEY_HOME,H1_KEY_H,H1_KEY_S,H1_KEY_P,H1_KEY_A};if(tab<5)return keys[tab];}
        return 0;
    }
    if(view==QM_VIEW_HOME){
        if(y>=120&&y<164&&x>=155)return x<305?H1_KEY_H:H1_KEY_S;
        if(y>=183&&y<241&&x>=155&&qm_current.mid[0])return H1_KEY_P;
        return 0;
    }
    if(view==QM_VIEW_ACCOUNT){if(x>=350){if(y>=72&&y<108)return H1_KEY_Q;if(y>=117&&y<153)return H1_KEY_W;if(y>=162&&y<198)return H1_KEY_R;if(y>=207&&y<243&&qm_account.logged)return H1_KEY_L;}return 0;}
    if(view==QM_VIEW_LIST){
        if(y<45&&x>=378)return x<424?H1_KEY_LEFT:H1_KEY_RIGHT;
        if(y>=67&&y<235){unsigned i=(unsigned)(y-67+list_offset)/42;return i<qm_songs.count?1000+(int)i:0;}
        return 0;
    }
    if(y<33&&x<85)return H1_KEY_ESCAPE;
    if(y<33&&x>=337)return H1_KEY_B;
    if(y>=201&&y<=221&&x>=20&&x<=460)return 2000+(x-20)*1000/440;
    if(y>=231){if(x<65)return H1_KEY_ESCAPE;if(x>=145&&x<202)return H1_KEY_N;if(x>=211&&x<270)return H1_KEY_SPACE;if(x>=279&&x<335)return H1_KEY_M;if(x>=375&&x<425)return H1_KEY_DOWN;if(x>=432)return H1_KEY_UP;}
    return 0;
}
