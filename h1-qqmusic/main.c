/* Independent native H1 music client; TMC's browse/queue/rights flow adapted to H1NET. */
#include "h1_sdk.h"
#include "firmware.h"
#include "transport.h"
#include "platform.h"
#include "app.h"
#include "queue.h"
#include "../h1-news/image.h"
#include "../src/platform/touch.h"
#include "../src/platform/audio.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include "font.h"
#include "../h1-bilibili/drawing.h"
#include "../h1-wifi/settings/style.h"
#undef UI_BLUE
#undef UI_TINT
#define UI_BLUE UI_RGB(0x0c8b62)
#define UI_TINT UI_RGB(0xe5f5ec)
#include "native_input.h"
volatile uint32_t qm_state[24]={0x31514d48u,1};
/* An observing deployment host can retain its session until its snapshot is
 * complete. It clears this application-owned flag before normal USB handoff. */
volatile uint32_t qm_debug_hold;
char qm_notice[160]="H 热歌榜  S 中文搜索  Enter 播放";
qm_list qm_songs;
qm_lyrics qm_words;
qm_track qm_current;
static qm_list play_queue;
static unsigned queue_index,rights_revision;
static qm_queue_policy queue_policy;
static unsigned play_mode,mode_dirty,end_handled;
static unsigned view=QM_VIEW_HOME,selected,page=1,search_mode,busy,closing,owned,open_ok,presents,inputs,volume=35;
static char query[64];static uint16_t *cover;static unsigned cover_w,cover_h;
static uint32_t clock_base,last_paint,last_ms,pen_sample;
static uint32_t last_parse_pump;
static unsigned pen_active,pen_drag,pen_list,ui_dirty;
static int list_offset,pen_start,pen_last,pen_x,pen_key;
static int panic_code,pending[16];static unsigned pending_read,pending_write;
static jmp_buf panic_return;
extern void h1ns_audio_snapshot(void);
extern volatile uint32_t h1ns_audio_state[8];
uint32_t qm_time(void){return clock_base+h1_timer_read_ms();}
uint32_t h1ns_time_ms(void){return qm_time();}
static void parse_audio_progress(void)
{if(qm_play.playing&&!qm_cancelled&&qm_time()-last_parse_pump>=24u){last_parse_pump=qm_time();qm_player_step();}}
void h1ns_panic(int code){panic_code=code;longjmp(panic_return,1);}
static int context_open(void){typedef int(*fn)(void);owned=((fn)h1_runtime_entry(h1_runtime_table(H1_RUNTIME_GUI_TABLE_SLOT),0x84c))();return owned;}
static void context_close(void){if(owned){typedef void(*fn)(void);((fn)h1_runtime_entry(h1_runtime_table(H1_RUNTIME_GUI_TABLE_SLOT),0x850))();owned=0;}}
static void message(const char *s){snprintf(qm_notice,sizeof qm_notice,"%s",s);}
static unsigned first_row(void){return (unsigned)list_offset/42;}
static int list_limit(void){return qm_songs.count>4?((int)qm_songs.count-4)*42:0;}
static void reveal_selected(void)
{
    int top=(int)selected*42;
    if(top<list_offset)list_offset=top;
    if(top+42>list_offset+168)list_offset=top+42-168;
    if(list_offset>list_limit())list_offset=list_limit();
}
static void publish(void)
{
    qm_state[2]=view;qm_state[3]=busy;qm_state[4]=qm_songs.count;qm_state[5]=selected;qm_state[6]=h1net_transport_connected();
    qm_state[11]=qm_play.playing;qm_state[12]=qm_play.ms;qm_state[13]=qm_play.duration;qm_state[14]=qm_play.pcm_bytes;
    qm_state[15]=qm_play.packets;qm_state[16]=qm_play.eof;qm_state[17]=qm_play.error;qm_state[18]=volume;
    qm_state[19]=qm_words.count;qm_state[20]=presents;qm_state[21]=inputs;qm_state[22]=(uint32_t)panic_code;qm_state[23]=closing;
}
#include "ui.h"
static void queue_key(int key)
{
    if(!key)return;
    if(busy){if(key==H1_KEY_ESCAPE||key==H1_KEY_BACK)qm_cancelled=1;return;}
    if(pending_write-pending_read<16)pending[pending_write++&15]=key;
}
static void pen_move(int x,int y)
{
    pen_x=x;
    if(!pen_drag&&abs(y-pen_start)>7)pen_drag=1;
    if(pen_drag&&pen_list&&!busy){
        list_offset+=pen_last-y;
        if(list_offset<0)list_offset=0;
        if(list_offset>list_limit())list_offset=list_limit();
        ui_dirty=1;
    }
    pen_last=y;
}
static void collect(void)
{
    for(unsigned i=0;i<32;i++){
        int code=-1,key=-1;h1_event_fetch(&code,&key);if(code==-1)break;
        if(code==H1_EVENT_KEY_DOWN){pen_active=0;queue_key(key);continue;}
        if(code!=11&&code!=12&&code!=8)continue;
        int x,y,valid=h1_touch_position(&x,&y);
        if(code==11&&valid){
            pen_active=1;pen_drag=0;pen_key=touch_key(x,y);
            pen_list=!view&&x>=137&&y>=67&&y<235;
            pen_x=x;pen_start=pen_last=y;pen_sample=qm_time();
        }else if(code==12&&pen_active&&valid)pen_move(x,y);
        else if(code==8&&pen_active){
            if(valid)pen_move(x,y);
            pen_active=0;
            if(!pen_drag&&pen_key==touch_key(valid?x:pen_x,valid?y:pen_last))queue_key(pen_key);
        }
    }
    if(pen_active&&pen_list&&qm_time()-pen_sample>=16u){
        int x,y;pen_sample=qm_time();
        if(h1_touch_position(&x,&y))pen_move(x,y);
    }
}
void qm_idle(void *unused)
{(void)unused;collect();if(busy&&qm_time()-last_paint>=200)qm_paint();}
static void start_busy(const char *s)
{busy=1;qm_cancelled=0;message(s);qm_paint();}
static void error_message(int error)
{if(qm_cancelled)message("已取消，按H或S重新开始");else if(!h1net_transport_connected())message("网络设备未连接，连接后按H或S重试");else snprintf(qm_notice,sizeof qm_notice,"网络或数据错误 %d，请重试",error);}
static void load_list(void)
{
    view=QM_VIEW_LIST;start_busy(search_mode?"正在搜索QQ音乐…":"正在读取热歌榜…");
    char url[401],*data=NULL;size_t length=0;int e=qm_search_url(query,page,(int)search_mode,url);qm_list *candidate=NULL;
    if(!e)e=qm_net_fetch(url,"GET",NULL,384u*1024u,&data,&length);
    if(!e){candidate=malloc(sizeof *candidate);char error[128];e=candidate?qm_parse_list(data,length,candidate,error):-1;
        if(!e){
            for(unsigned i=0;i<candidate->count;i++)for(unsigned j=0;j<play_queue.count;j++)
                if((play_queue.tracks[j].paid&QM_RIGHTS_PLAYABLE)&&!strcmp(candidate->tracks[i].mid,play_queue.tracks[j].mid))candidate->tracks[i].paid|=QM_RIGHTS_PLAYABLE;
            qm_songs=*candidate;selected=0;list_offset=0;pen_active=0;message(qm_songs.count?"上下选择 / Enter播放 / 左右翻页":"没有搜索结果，按S更换关键词");}else message(candidate?error:"内存不足");
    }else error_message(e);
    free(candidate);free(data);busy=0;qm_cancelled=0;qm_paint();
}
/* 1 = unavailable rights, negative = transport/cancel; auto-skip only rights. */
static int play_queued(int background)
{
    if(queue_index>=play_queue.count)return -1;qm_track candidate=play_queue.tracks[queue_index];int outcome=0;
    if((candidate.paid&QM_RIGHTS_MASK)==QM_RIGHTS_MEMBER&&!qm_account.logged){message("该歌曲需要账号授权，请在账号页登录");qm_paint();return 1;}
    end_handled=0;qm_player_close();free(cover);cover=NULL;cover_w=cover_h=0;memset(&qm_words,0,sizeof qm_words);qm_current=candidate;if(!background)view=1;start_busy("正在取得歌曲播放地址…");
    char body[640],url[401],media[401],*data=NULL;size_t length=0;int e=qm_vkey_body(&qm_current,qm_time()+1000000000u,body);
    if(e<0)goto done;e=qm_net_fetch("https://u.y.qq.com/cgi-bin/musicu.fcg","POST",body,64*1024,&data,&length);
    if(e)goto done;char error[128];e=qm_parse_url(data,length,qm_current.mid,media,error);free(data);data=NULL;if(e){
        qm_current.paid&=QM_RIGHTS_MASK;play_queue.tracks[queue_index].paid&=QM_RIGHTS_MASK;
        for(unsigned i=0;i<qm_songs.count;i++)if(!strcmp(qm_songs.tracks[i].mid,qm_current.mid))qm_songs.tracks[i].paid&=QM_RIGHTS_MASK;
        message(error);qm_play.error=1;outcome=e==1?1:-1;goto finish;}
    message("正在加载歌词和封面…");qm_paint();
    snprintf(url,sizeof url,"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?format=json&nobase64=1&g_tk=5381&songmid=%s",qm_current.mid);
    if(!qm_net_fetch(url,"GET",NULL,64*1024,&data,&length)){(void)qm_parse_lyrics(data,length,&qm_words);free(data);data=NULL;}
    if(qm_cancelled){e=-6;goto done;}
    if(!qm_cover_url(&qm_current,url)&&!qm_net_fetch(url,"GET",NULL,256*1024,&data,&length)){(void)news_image_decode((uint8_t *)data,(unsigned)length,&cover,&cover_w,&cover_h,148,148);free(data);data=NULL;}
    if(qm_cancelled){e=-6;goto done;}message("正在缓冲M4A音频…");qm_paint();e=qm_player_open(media);
    if(!e){
        qm_current.paid|=QM_RIGHTS_PLAYABLE;play_queue.tracks[queue_index].paid|=QM_RIGHTS_PLAYABLE;
        for(unsigned i=0;i<qm_songs.count;i++)if(!strcmp(qm_songs.tracks[i].mid,qm_current.mid))qm_songs.tracks[i].paid|=QM_RIGHTS_PLAYABLE;
        gba_audio_set_volume(volume);message("空格暂停 / 左右快进 / 上下调音量");goto finish;}
done:error_message(e);qm_player_close();qm_play.error=1;outcome=-1;
finish:free(data);busy=0;qm_paint();return outcome;
}
static void play_selected(void)
{
    if(selected>=qm_songs.count)return;
    if((qm_songs.tracks[selected].paid&QM_RIGHTS_MASK)==QM_RIGHTS_MEMBER&&!qm_account.logged){message("该歌曲需要账号授权，请在账号页登录");qm_paint();return;}
    play_queue=qm_songs;queue_index=selected;qm_queue_begin(&queue_policy,play_queue.count,queue_index,play_mode,qm_time());(void)play_queued(0);
}
static void advance_queue(int action)
{
    unsigned visited=0,old=queue_index;int background=action==QM_QUEUE_ENDED&&view!=QM_VIEW_PLAYER;
    for(unsigned attempts=0;attempts<play_queue.count;attempts++){
        unsigned next=qm_queue_move(&queue_policy,action);
        if(next==QM_TRACKS){message(action==QM_QUEUE_PREVIOUS?"已是第一首":action==QM_QUEUE_ENDED?"本页队列播放完毕":"已是最后一首");break;}
        if(visited&(1u<<next))break;visited|=1u<<next;queue_index=next;
        int result=play_queued(background);if(result<=0)break;
        if(action!=QM_QUEUE_ENDED||play_mode==QM_PLAY_SINGLE_LOOP)break;
    }
    /* EOF is handled once, including an exhausted/unavailable queue. */
    end_handled=qm_play.eof||!qm_play.playing;
    if(action!=QM_QUEUE_ENDED&&old==queue_index)ui_dirty=1;
    qm_paint();
}
static void mode_load(void)
{
    uint8_t b[16];h1_file *f=h1_fopen("A:\\QQMusic.cfg","rb");if(!f)return;
    unsigned n=h1_fread(b,1,sizeof b,f);h1_fclose(f);
    if(n==16&&h1net_u32(b)==0x31434d51u&&h1net_u32(b+4)==1&&h1net_u32(b+8)<QM_PLAY_MODES&&h1net_u32(b+12)==h1net_crc32(b,12))play_mode=h1net_u32(b+8);
}
static void mode_save(void)
{
    if(!mode_dirty)return;uint8_t b[16];h1net_put32(b,0x31434d51u);h1net_put32(b+4,1);h1net_put32(b+8,play_mode);h1net_put32(b+12,h1net_crc32(b,12));
    h1_file *f=h1_fopen("A:\\QQMusic.cfg","wb");if(f){(void)h1_fwrite(b,1,sizeof b,f);h1_fclose(f);}
}
static void invalidate_rights(void)
{
    if(rights_revision==qm_account_revision)return;rights_revision=qm_account_revision;
    for(unsigned i=0;i<qm_songs.count;i++)qm_songs.tracks[i].paid&=QM_RIGHTS_MASK;
    for(unsigned i=0;i<play_queue.count;i++)play_queue.tracks[i].paid&=QM_RIGHTS_MASK;
    qm_current.paid&=QM_RIGHTS_MASK;ui_dirty=1;
}
static void search(void)
{
    qm_player_before_input();uint32_t held=qm_time();h1ns_heap_trim();h1_timer_stop();context_close();int ok=qm_native_input_raw(query,sizeof query);
    if(!context_open())h1ns_panic(2701);h1_timer_start();clock_base=held;qm_net_reset();
    qm_cancelled=0;if(qm_player_after_input())message("音乐恢复失败，请重新点播");gba_audio_set_volume(volume);
    if(ok){if(!query[0]||strlen(query)>48)message("搜索词需要1～48字节，请缩短后重试");else{page=1;search_mode=1;load_list();}}
    qm_paint();
}
static void acquire_usb(void);
static void key_action(int key)
{
    inputs++;
    if(!open_ok&&key!=H1_KEY_ESCAPE&&key!=H1_KEY_BACK){
        acquire_usb();if(!open_ok)return;
    }
    if(key>=2000){if(view&&qm_play.ready&&qm_play.duration){int64_t target=(int64_t)qm_play.duration*(key-2000)/1000,delta=target-qm_play.ms;if(qm_player_seek((int)(delta>=0?(delta+500)/1000:(delta-500)/1000)))message("定位失败，请重新播放");}qm_paint();return;}if(key>=1000){selected=(unsigned)(key-1000);play_selected();return;}
    if(key==H1_KEY_ESCAPE||key==H1_KEY_BACK){if(view==QM_VIEW_PLAYER||view==QM_VIEW_ACCOUNT){if(view==QM_VIEW_ACCOUNT)qm_account_cancel();view=qm_songs.count?QM_VIEW_LIST:QM_VIEW_HOME;message(qm_play.playing?"音乐继续播放，左侧可返回正在播放":"上下选择歌曲，Enter播放");}else closing=1;}
    else if(key==QM_KEY_HOME){if(view==QM_VIEW_ACCOUNT)qm_account_cancel();view=QM_VIEW_HOME;}
    else if(key==H1_KEY_A){view=QM_VIEW_ACCOUNT;message("Q QQ扫码 / W 微信扫码 / R刷新 / L退出登录");}
    else if(key==H1_KEY_P&&view!=QM_VIEW_PLAYER){if(view==QM_VIEW_ACCOUNT)qm_account_cancel();if(qm_current.mid[0])view=QM_VIEW_PLAYER;else message("尚未选择歌曲，先搜索或打开热歌榜");}
    else if(key==H1_KEY_H){if(view==QM_VIEW_ACCOUNT)qm_account_cancel();page=1;search_mode=0;load_list();}
    else if(key==H1_KEY_S){if(view==QM_VIEW_ACCOUNT)qm_account_cancel();view=QM_VIEW_LIST;search();}
    else if(view==QM_VIEW_ACCOUNT){
        if(key==H1_KEY_Q||key==H1_KEY_W||key==H1_KEY_R)qm_account_begin(key==H1_KEY_W?1:key==H1_KEY_Q?2:qm_account.kind?qm_account.kind:2);
        else if(key==H1_KEY_L)(void)qm_account_logout();
    }
    else if(key==H1_KEY_B){play_mode=(play_mode+1)%QM_PLAY_MODES;mode_dirty=1;qm_queue_mode(&queue_policy,play_mode);message(qm_queue_label(play_mode));}
    else if(view==1){
        if(key==H1_KEY_ENTER||key==H1_KEY_SPACE||key==H1_KEY_P){
            end_handled=0;if(!qm_play.ready||qm_play.error)(void)play_queued(0);else qm_player_toggle();
        }
        else if(key==H1_KEY_LEFT||key==H1_KEY_RIGHT){if(qm_player_seek(key==H1_KEY_LEFT?-10:10))message("定位失败，请重新播放");}
        else if(key==H1_KEY_UP||key==H1_KEY_DOWN){if(key==H1_KEY_UP){if(volume<100)volume+=5;}else if(volume>=5)volume-=5;gba_audio_set_volume(volume);}
        else if(key==H1_KEY_N||key==H1_KEY_M)advance_queue(key==H1_KEY_N?QM_QUEUE_PREVIOUS:QM_QUEUE_NEXT);
    }
    else if(view==QM_VIEW_HOME){if(key==H1_KEY_ENTER||key==H1_KEY_CONFIRM){page=1;search_mode=0;load_list();}}
    else if(key==H1_KEY_ENTER||key==H1_KEY_CONFIRM)play_selected();
    else if(key==H1_KEY_UP){if(selected)selected--;}
    else if(key==H1_KEY_DOWN){if(selected+1<qm_songs.count)selected++;}
    else if(key==H1_KEY_LEFT||key==H1_KEY_RIGHT){if(key==H1_KEY_LEFT){if(page>1)page--;else return;}else if(page<999)page++;load_list();}
    if(!view)reveal_selected();qm_paint();
}
static int debug_active(void)
{
#ifndef H1NET_DEBUG_TRANSPORT
    rd_header *debug=fw_task_control();
    return debug && debug->state!=RD_STOPPED;
#else
    return 0;
#endif
}
static void acquire_usb(void)
{
    pen_active=0;
    if(debug_active()){
        message("正在准备网络连接…");qm_paint();
        uint32_t start=qm_time();
        while(!closing&&debug_active()){
            /* Allow a deploying host to finish observing the startup frame.
             * Normal launch then cooperatively stops the existing resident. */
#ifndef H1NET_DEBUG_TRANSPORT
            if(!qm_debug_hold&&qm_time()-start>=4000u){rd_header *debug=fw_task_control();if(debug)debug->stop_request=1;}
#endif
            collect();
            while(pending_read!=pending_write){
                int key=pending[pending_read++&15];
                if(key==H1_KEY_ESCAPE||key==H1_KEY_BACK)closing=1;
            }
            if(!qm_debug_hold&&qm_time()-start>=9000u){message("网络连接暂不可用，请稍后重试");qm_paint();return;}
            fw_delay(1);
        }
    }
    if(closing)return;
    open_ok=qm_net_open()==0;
    message(open_ok?"H热歌榜 / S搜索 / A账号":"连接暂不可用，按H或S重试");
    qm_paint();
}
int h1_app_main(void)
{
    if(!fw_matches()||!context_open())return 1;h1_timer_start();h1ns_io_init();
    if(!setjmp(panic_return)){
        qm_set_parse_progress(parse_audio_progress);mode_load();qm_account_init();acquire_usb();
        while(!closing){h1net_transport_poll();
            unsigned was_playing=qm_play.playing;
            unsigned previous_connection=qm_connection_status;
            qm_net_probe_step(!busy&&!qm_play.ready);
            if(previous_connection!=qm_connection_status)ui_dirty=1;
            if(h1net_transport_faulted()){
                qm_player_close();qm_net_close();open_ok=0;view=0;
                pending_read=pending_write;acquire_usb();continue;
            }
            collect();while(pending_read!=pending_write&&!closing&&!qm_net_probe_active())key_action(pending[pending_read++&15]);
            if(!closing&&!busy&&(view==QM_VIEW_ACCOUNT||!qm_play.ready)&&!qm_net_probe_active()&&qm_connection_status==QM_NETWORK_READY){
                unsigned previous=qm_account.state;busy=1;qm_cancelled=0;qm_account_step(view==2);busy=0;
                if(previous!=qm_account.state)ui_dirty=1;
                if(qm_cancelled){qm_account_cancel();view=qm_songs.count?QM_VIEW_LIST:QM_VIEW_HOME;qm_cancelled=0;message("已取消扫码");ui_dirty=1;}
            }
            invalidate_rights();
            if(!closing&&qm_play.playing)qm_player_step();
            if(!closing&&!busy&&qm_play.eof&&!end_handled)advance_queue(QM_QUEUE_ENDED);
            if(qm_play.error&&was_playing&&qm_player_diag[2])snprintf(qm_notice,sizeof qm_notice,"播放中断 %u/%ld，空格重试",(unsigned)qm_player_diag[2],(long)(int32_t)qm_player_diag[3]);
            if(was_playing!=qm_play.playing)ui_dirty=1;
            if(ui_dirty||(view==QM_VIEW_PLAYER&&qm_play.ms!=last_ms&&qm_time()-last_paint>=150)){last_ms=qm_play.ms;qm_paint();}if(!qm_play.playing)fw_delay(1);
        }
    }
    qm_account_close();qm_player_close();if(!panic_code)mode_save();free(cover);cover=NULL;if(open_ok)qm_net_close();h1ns_io_release();h1ns_heap_release();h1_timer_stop();context_close();publish();return panic_code;
}
