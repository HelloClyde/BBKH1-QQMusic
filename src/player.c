/* Audio-only MOV/M4A demux on H1; original AAC packets decoded by generic ESP worker. */
#include "app.h"
#include "h1net_wire.h"
#include "h1_sdk.h"
#include "libavformat/avformat.h"
#include "libavcodec/avcodec.h"
#include "h1_aac.h"
#include "h1_media_audio.h"
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static h1_aac decoder;
volatile uint32_t qm_aac_state[16];
static int aac_rpc(void *p,unsigned op,const void *in,unsigned n,void *out,unsigned cap,unsigned *got)
{(void)p;return qm_net_compute_rpc(op,in,n,out,cap,got);}
static unsigned aac_features(void *p){(void)p;return qm_net_features();}
static uint32_t aac_time(void *p){(void)p;return h1_timer_read_ms();}
static void aac_idle(void *p){(void)p;qm_idle(NULL);}
static int aac_cancelled(void *p){(void)p;return qm_cancelled;}
static int decoder_open(const uint8_t *asc,unsigned n)
{
    static unsigned initialized;
    if(!initialized){h1_aac_driver d={NULL,aac_rpc,aac_features,aac_time,aac_idle,aac_cancelled};
        h1_aac_init(&decoder,&d,qm_aac_state);initialized=1;}
    return h1_aac_open(&decoder,asc,n);
}
qm_player_state qm_play;
/* Retained on normal exit; contains counters/error codes only, no URLs/tokens. */
volatile uint32_t qm_player_diag[16]={0x31444d51u,1};
/* Retained buffering observations, no account/URL data. */
volatile uint32_t qm_buffer_diag[16]={0x31424d51u,1};
static struct {char url[401];unsigned ms,playing,valid;} input_resume;
enum {CACHE_BYTES=4096};
static unsigned formats_initialized;
static struct {
    AVFormatContext *format;ByteIOContext io;int ai;
    char url[401];uint32_t size,offset,age,starts[2],sizes[2],ages[2],base_ms,anchor_ms,origin_ms;
    uint8_t *cache[2];int16_t pcm[4096];
    unsigned finished,anchor,paused_seek,io_error,tail_padded,clock_seen,clock_recover,last_underruns;
    uint32_t remote_produced,remote_poll_ms;
    unsigned remote_known,prefilling;
} v;
enum {PCM_START_BYTES=49152,PCM_AHEAD_BYTES=65536};
static unsigned remote_pending(void)
{return v.remote_produced>=qm_aac_state[8]?v.remote_produced-qm_aac_state[8]:0;}
static int remote_level(int force)
{
    if(!force&&v.remote_known&&qm_time()-v.remote_poll_ms<50)return 0;
    h1_aac_info info;int e=h1_aac_get_info(&decoder,&info);if(e)return e;
    v.remote_produced=info.produced;v.remote_poll_ms=qm_time();v.remote_known=1;
    qm_buffer_diag[2]++;qm_buffer_diag[3]=remote_pending();
    if(remote_pending()>qm_buffer_diag[4])qm_buffer_diag[4]=remote_pending();return 0;
}
int qm_player_buffering(void){return qm_play.ready&&qm_play.playing&&v.prefilling;}
static void diagnostic(unsigned reason,int result)
{
    h1ns_audio_snapshot();qm_player_diag[2]=reason;qm_player_diag[3]=(uint32_t)result;
    qm_player_diag[4]=qm_play.ms;qm_player_diag[5]=qm_play.packets;qm_player_diag[6]=qm_play.pcm_bytes;
    qm_player_diag[7]=v.offset;qm_player_diag[8]=qm_aac_state[8];
    qm_player_diag[9]=h1ns_audio_state[7];qm_player_diag[10]=h1ns_audio_state[5];qm_player_diag[11]=h1ns_audio_state[6];
    qm_player_diag[13]=qm_state[10];
}
static int read_bytes(void *unused,uint8_t *out,int wanted)
{
    (void)unused;if(qm_cancelled)return AVERROR(EIO);if(wanted<=0)return 0;
    unsigned remaining=v.size-v.offset;if((unsigned)wanted>remaining)wanted=(int)remaining;if(!wanted)return AVERROR_EOF;
    unsigned copied=0;
    while(copied<(unsigned)wanted){unsigned slot=2;
        for(unsigned i=0;i<2;i++)if(v.sizes[i]&&v.offset>=v.starts[i]&&v.offset-v.starts[i]<v.sizes[i]){slot=i;break;}
        if(slot==2){slot=v.ages[0]<=v.ages[1]?0:1;uint32_t start=v.offset&~(CACHE_BYTES-1u),n=v.size-start;if(n>CACHE_BYTES)n=CACHE_BYTES;
            if(!v.cache[slot])v.cache[slot]=malloc(CACHE_BYTES);if(!v.cache[slot])return AVERROR(ENOMEM);
            v.sizes[slot]=0;int e=qm_net_stream(v.url,start,n,v.size,v.cache[slot]);if(e){diagnostic(10,e);v.io_error=1;return AVERROR(EIO);}
            v.starts[slot]=start;v.sizes[slot]=n;}
        unsigned n=v.sizes[slot]-(v.offset-v.starts[slot]);if(n>(unsigned)wanted-copied)n=(unsigned)wanted-copied;
        memcpy(out+copied,v.cache[slot]+v.offset-v.starts[slot],n);v.offset+=n;copied+=n;v.ages[slot]=++v.age;
    }return (int)copied;
}
static int64_t seek_bytes(void *unused,int64_t offset,int whence)
{
    (void)unused;if(whence==AVSEEK_SIZE)return v.size;
    int64_t base=whence==SEEK_SET?0:whence==SEEK_CUR?v.offset:whence==SEEK_END?v.size:-INT64_MAX;
    if(base==-INT64_MAX||offset<-base||offset>(int64_t)v.size-base)return AVERROR(EINVAL);v.offset=(uint32_t)(base+offset);return v.offset;
}
static void position(void)
{
    uint32_t played;unsigned buffered;
    if(v.anchor){
        if(h1ns_audio_clock(&played,&buffered)){qm_play.ms=v.anchor_ms+played;v.clock_seen=1;}
        else {h1ns_audio_snapshot();if(qm_play.playing&&(v.clock_seen||h1ns_audio_state[7]!=v.last_underruns))v.clock_recover=1;}
    }
    if(qm_play.duration&&qm_play.ms>qm_play.duration)qm_play.ms=qm_play.duration;
}
static int recover_clock(void)
{
    /* Only the native ring is touched: safe even in AAC PUSH's PCM progress
     * callback. The decoder, HTTP cursor and demux state keep their ownership. */
    qm_buffer_diag[6]++;qm_buffer_diag[7]=remote_pending();qm_buffer_diag[8]=qm_play.ms;
    qm_buffer_diag[9]=qm_stream_diag[7];qm_buffer_diag[10]=qm_stream_diag[8];
    qm_buffer_diag[11]=qm_time()-v.remote_poll_ms;qm_buffer_diag[12]=qm_play.packets;
    uint32_t next=v.origin_ms+(uint32_t)((uint64_t)qm_aac_state[8]*1000u/65536u);
    gba_audio_pause();h1ns_audio_clock_reset();
    if(!gba_audio_resume()){diagnostic(4,-1);return -1;}
    v.anchor_ms=next;v.clock_seen=v.clock_recover=v.tail_padded=0;v.prefilling=1;
    h1ns_audio_snapshot();v.last_underruns=h1ns_audio_state[7];
    qm_player_diag[12]++;qm_player_diag[15]=next;return 0;
}
static int pump(void *unused)
{
    (void)unused;position();if(v.clock_recover&&recover_clock())return -1;if(v.prefilling||h1ns_audio_video_wait())return 0;
    int e=remote_level(!v.remote_known||!remote_pending());if(e){diagnostic(9,e);return e;}
    unsigned capacity=remote_pending();if(capacity>4096)capacity=4096;if(!capacity)return 0;
    unsigned bytes=0;e=h1_aac_read(&decoder,(uint8_t *)v.pcm,capacity,&bytes);if(e){diagnostic(1,e);return e;}if(!bytes)return 0;
    unsigned count=bytes/2;for(unsigned i=count;i-->0;)v.pcm[2*i]=v.pcm[2*i+1]=v.pcm[i];
    if(gba_audio_write(v.pcm,count)!=count){diagnostic(2,-1);return -1;}qm_play.pcm_bytes+=bytes;h1ns_audio_snapshot();
    if(!h1ns_audio_state[0]||h1ns_audio_state[5]||h1ns_audio_state[6]){diagnostic(3,-1);return -1;}position();return (int)bytes;
}
void qm_player_network_idle(void)
{
    /* Invoked only between completed HTTP RPCs. The shared client is idle,
     * so fetching decoded PCM here cannot overwrite an in-flight response. */
    if(qm_play.ready&&qm_play.playing&&!qm_play.error&&pump(NULL)<0){
        qm_play.error=1;qm_play.playing=0;gba_audio_pause();
    }
}
void qm_player_close(void)
{
    gba_audio_close();if(decoder.state)h1_aac_close(&decoder);qm_net_stream_close();
    if(v.format)av_close_input_stream(v.format);av_free(v.io.buffer);free(v.cache[0]);free(v.cache[1]);
    memset(&v,0,sizeof v);v.ai=-1;memset(&qm_play,0,sizeof qm_play);
}
int qm_player_open(const char *url)
{
    qm_player_close();for(unsigned i=2;i<16;i++)qm_player_diag[i]=qm_buffer_diag[i]=0;if(!url||strlen(url)>400)return -1;
    if(!(qm_net_features()&H1NET_CAP_AUDIO_AAC)){qm_play.error=2;return -1;}
    memcpy(v.url,url,strlen(url)+1);if(qm_net_size(url,&v.size))goto fail;
    av_log_set_level(AV_LOG_ERROR);avcodec_init();extern AVInputFormat mov_demuxer;
    if(!formats_initialized){av_register_input_format(&mov_demuxer);formats_initialized=1;}
    uint8_t *buffer=av_malloc(4096);if(!buffer)goto fail;init_put_byte(&v.io,buffer,4096,0,NULL,read_bytes,NULL,seek_bytes);
    if(av_open_input_stream(&v.format,&v.io,"h1.m4a",&mov_demuxer,NULL)<0)goto fail;
    for(unsigned i=0;i<v.format->nb_streams;i++)if(v.format->streams[i]->codec->codec_type==AVMEDIA_TYPE_AUDIO&&v.format->streams[i]->codec->codec_id==CODEC_ID_AAC){v.ai=(int)i;break;}
    if(v.ai<0)goto fail;AVCodecContext *audio=v.format->streams[v.ai]->codec;
    if(audio->channels<1||audio->channels>2||audio->extradata_size<=0||!decoder_open(audio->extradata,(unsigned)audio->extradata_size))goto fail;
    if(!gba_audio_open(32768))goto fail;gba_audio_set_volume(35);h1ns_audio_clock_reset();h1_aac_set_progress(&decoder,pump,NULL);
    AVStream *stream=v.format->streams[v.ai];
    if(stream->duration>0&&stream->duration<(int64_t)INT64_MAX/1000){int64_t ms=av_rescale_q(stream->duration,stream->time_base,(AVRational){1,1000});if(ms>0&&ms<86400000)qm_play.duration=(unsigned)ms;}
    if(!qm_play.duration&&v.format->duration>0&&v.format->duration<86400ll*AV_TIME_BASE)qm_play.duration=(unsigned)(v.format->duration/1000);
    v.prefilling=1;qm_play.ready=qm_play.playing=1;return 0;
fail:qm_player_close();qm_play.error=1;return -1;
}
void qm_player_step(void)
{
    if(!qm_play.ready||!qm_play.playing)return;position();
    if(v.clock_recover){
        /* The next decoded sample has a known media position: READ's PCM byte
         * offset at 32768Hz, relative to the first submitted packet PTS. Keep
         * MOV/AAC/HTTP intact. Discard the native ring, then rebase its clock
         * onto that next sample; no wall time or ambiguous cursor is counted. */
        if(recover_clock())goto fail;
        return;
    }
    int e=remote_level(!v.remote_known||remote_pending()<PCM_AHEAD_BYTES);if(e){diagnostic(9,e);goto fail;}
    if(v.prefilling&&(remote_pending()>=PCM_START_BYTES||v.finished)){v.prefilling=0;qm_buffer_diag[5]++;}
    e=pump(NULL);if(e<0)goto fail;
    if(v.finished){e=h1_aac_eof(&decoder);if(e<0){diagnostic(5,e);goto fail;}
        unsigned pending=h1ns_audio_pending();h1ns_audio_snapshot();
        /* V1.41 starts the persistent mixer ring after 4096 samples. A short
         * final/seek segment must be padded to that threshold so its real PCM
         * can retire; otherwise EOS waits forever for a ring that never starts. */
        if(e&&pending&&!h1ns_audio_state[1]&&!v.tail_padded){
            unsigned frames=((4096u-pending)*32768u+31999u)/32000u;memset(v.pcm,0,sizeof v.pcm);
            while(frames){unsigned n=frames>2048?2048:frames;gba_audio_write(v.pcm,n);frames-=n;}v.tail_padded=1;
        }
        if(e&&!pending){qm_play.playing=0;qm_play.eof=1;if(qm_play.duration)qm_play.ms=qm_play.duration;}return;}
    /* Keep the existing ESP PCM ring ~1 s ahead even when the native ring is
     * full. Previously that condition stopped demux/AAC feeding altogether,
     * leaving almost no decoded reserve and many empty AUDIO_READ polls. */
    if(remote_pending()>=PCM_AHEAD_BYTES)return;
    AVPacket packet;av_init_packet(&packet);packet.data=NULL;packet.size=0;
    int r=av_read_frame(v.format,&packet);
    if(r<0){if(qm_cancelled||v.io_error||r!=AVERROR_EOF){if(!qm_player_diag[2])diagnostic(6,r);goto fail;}int done=h1_aac_finish(&decoder);if(done){diagnostic(8,done);goto fail;}v.finished=1;return;}
    if(packet.stream_index==v.ai){
        int64_t pts=packet.pts==(int64_t)AV_NOPTS_VALUE?(int64_t)v.base_ms:av_rescale_q(packet.pts,v.format->streams[v.ai]->time_base,(AVRational){1,1000});
        if(pts<0)pts=0;if(!v.anchor){v.anchor=1;v.origin_ms=v.anchor_ms=(uint32_t)pts;}
        e=h1_aac_push(&decoder,packet.data,(unsigned)packet.size,(uint32_t)pts);qm_play.packets++;
    }
    av_free_packet(&packet);if(e<0){if(!qm_player_diag[2])diagnostic(7,e);goto fail;}return;
fail:qm_play.error=1;qm_play.playing=0;gba_audio_pause();
}
int qm_player_seek(int seconds)
{
    if(!qm_play.ready||v.ai<0)return -1;int64_t target=(int64_t)qm_play.ms+(int64_t)seconds*1000;
    if(target<0)target=0;if(qm_play.duration&&target>=(int64_t)qm_play.duration)target=qm_play.duration>1000?qm_play.duration-1000:0;
    int playing=qm_play.playing;gba_audio_pause();qm_net_stream_close();
    if(h1_aac_reset(&decoder))return -1;
    int64_t stamp=av_rescale_q(target,(AVRational){1,1000},v.format->streams[v.ai]->time_base);
    if(av_seek_frame(v.format,v.ai,stamp,AVSEEK_FLAG_BACKWARD)<0)return -1;
    v.finished=v.anchor=v.io_error=v.tail_padded=v.clock_seen=v.clock_recover=v.remote_known=0;v.prefilling=1;
    v.remote_produced=0;v.base_ms=(uint32_t)target;qm_play.ms=(unsigned)target;qm_play.eof=qm_play.error=0;
    h1ns_audio_snapshot();v.last_underruns=h1ns_audio_state[7];
    h1ns_audio_clock_reset();if(playing&&!gba_audio_resume())return -1;return 0;
}
void qm_player_toggle(void)
{
    if(!qm_play.ready)return;
    if(qm_play.playing){position();qm_play.playing=0;gba_audio_pause();v.paused_seek=1;}
    else {if((v.paused_seek||qm_play.eof)&&qm_player_seek(qm_play.eof?-(int)(qm_play.ms/1000):0)){qm_play.error=1;return;}
        v.paused_seek=0;if(gba_audio_resume())qm_play.playing=1;else qm_play.error=1;}
}
void qm_player_before_input(void)
{
    memset(&input_resume,0,sizeof input_resume);
    if(!qm_play.ready)return;
    position();strcpy(input_resume.url,v.url);input_resume.ms=qm_play.ms;
    input_resume.playing=qm_play.playing;input_resume.valid=1;qm_player_close();
}
int qm_player_after_input(void)
{
    if(!input_resume.valid)return 0;
    input_resume.valid=0;
    int e=qm_player_open(input_resume.url);
    if(!e&&input_resume.ms)e=qm_player_seek((int)(input_resume.ms/1000));
    if(!e&&!input_resume.playing)qm_player_toggle();
    memset(&input_resume,0,sizeof input_resume);return e;
}
