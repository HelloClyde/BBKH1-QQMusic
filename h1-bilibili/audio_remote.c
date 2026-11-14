/* Stateful AAC offload over the same generic H1NET bus as HTTP. One audio
 * session is independent of the four HTTP jobs. No video bytes are changed. */
#include "audio_remote.h"
#include "app.h"
#include "h1_sdk.h"
#include "h1net_wire.h"
#include "h1net_client.h"
#include <string.h>
volatile uint32_t bili_audio_remote_enable=1;
/* magic/schema, requested, capability, active, job, error, input/output bytes,
 * pushed frames, reads, empty reads, finished, PCM FNV, resets, reserved. */
volatile uint32_t bili_audio_remote_state[16]={0x31415242u,1};
static uint32_t job,sequence,output_offset;
static int (*progress_pcm)(void *);
static void *progress_context;
static int in_progress;
void bili_audio_remote_set_progress(int (*fn)(void *),void *context)
{progress_pcm=fn;progress_context=context;}
static int call(unsigned op,const void *p,unsigned n,void *out,unsigned capacity,unsigned *used)
{
    int e=bili_net_compute_rpc(op,p,n,out,capacity,used);
    /* BUSY explicitly leaves a fragment unconsumed; the PUSH retry below
       is normal backpressure, not a sticky decoder/transport failure. */
    if(e&&e!=-102)bili_audio_remote_state[6]=(uint32_t)e;
    return e;
}
static int job_call(unsigned op)
{
    uint8_t p[4];unsigned used=0;h1net_put32(p,job);
    int e=call(op,p,4,NULL,0,&used);return e?e:used?-3:0;
}
void bili_audio_remote_close(void)
{
    if(job)(void)job_call(H1NET_AUDIO_CLOSE);
    job=sequence=output_offset=0;bili_audio_remote_state[4]=bili_audio_remote_state[5]=0;
    progress_pcm=NULL;progress_context=NULL;in_progress=0;
}
int bili_audio_remote_open(const uint8_t *asc,unsigned n)
{
    bili_audio_remote_close();for(unsigned i=2;i<16;i++)bili_audio_remote_state[i]=0;
    bili_audio_remote_state[2]=bili_audio_remote_enable;
    if(!bili_audio_remote_enable)return 0;
    unsigned features=bili_net_features();bili_audio_remote_state[3]=!!(features&H1NET_CAP_AUDIO_AAC);
    if(!(features&H1NET_CAP_AUDIO_AAC)||!asc||!n||n>64)return 0;
    uint8_t p[80],reply[4];unsigned used=0;
    h1net_put32(p,1);h1net_put32(p+4,32768);h1net_put32(p+8,1);h1net_put32(p+12,n);memcpy(p+16,asc,n);
    int e=call(H1NET_AUDIO_OPEN,p,16+n,reply,4,&used);
    if(e||used!=4||!(job=h1net_u32(reply)))return 0;
    sequence=output_offset=0;bili_audio_remote_state[4]=1;bili_audio_remote_state[5]=job;bili_audio_remote_state[13]=2166136261u;return 1;
}
int bili_audio_remote_push(const uint8_t *data,unsigned n,uint32_t pts)
{
    if(!job||!data||!n||n>16384||in_progress)return -3;
    uint8_t p[512],reply[4];unsigned offset=0;
    while(offset<n){
        unsigned count=n-offset;if(count>492)count=492;
        h1net_put32(p,job);h1net_put32(p+4,sequence);h1net_put32(p+8,n);h1net_put32(p+12,offset);h1net_put32(p+16,pts);memcpy(p+20,data+offset,count);
        unsigned used=0;uint32_t start=h1_timer_read_ms();int e;
        do{
            e=call(H1NET_AUDIO_PUSH,p,20+count,reply,4,&used);
            if(e!=-102)break;
            if(bili_cancelled)return -6;
            if(progress_pcm){
                in_progress=1;int advanced=progress_pcm(progress_context);in_progress=0;
                if(advanced<0){bili_audio_remote_state[6]=(uint32_t)advanced;return advanced;}
                if(advanced)start=h1_timer_read_ms();
            }
            bili_idle(NULL);
        }while(h1_timer_read_ms()-start<1000);
        if(e==-102){bili_audio_remote_state[6]=(uint32_t)H1NET_TIMEOUT;return H1NET_TIMEOUT;}
        if(e)return e;if(used!=4||h1net_u32(reply)!=offset+count)return -3;offset+=count;
    }
    ++sequence;++bili_audio_remote_state[9];bili_audio_remote_state[7]+=n;return 0;
}
int bili_audio_remote_read(uint8_t *out,unsigned capacity,unsigned *received)
{
    if(!job||!out||!received||capacity<2)return -3;*received=0;capacity&=~1u;
    while(*received<capacity){
        unsigned wanted=capacity-*received;if(wanted>500)wanted=500;
        uint8_t p[8],reply[512];unsigned used=0;
        h1net_put32(p,job);h1net_put32(p+4,wanted);
        int e=call(H1NET_AUDIO_READ,p,8,reply,512,&used);if(e)return e;
        ++bili_audio_remote_state[10];
        if(used<12||h1net_u32(reply)!=job||h1net_u32(reply+4)!=output_offset)return -3;
        unsigned n=h1net_u32(reply+8);if(n>wanted||used!=12+n||(n&1))return -3;
        if(!n){++bili_audio_remote_state[11];break;}
        memcpy(out+*received,reply+12,n);*received+=n;output_offset+=n;
        uint32_t hash=bili_audio_remote_state[13];for(unsigned i=0;i<n;i++)hash=(hash^reply[12+i])*16777619u;bili_audio_remote_state[13]=hash;
        if(n<wanted)break;
    }
    bili_audio_remote_state[8]=output_offset;return 0;
}
int bili_audio_remote_reset(void)
{
    if(!job)return 0;int e=job_call(H1NET_AUDIO_RESET);if(e)return e;
    sequence=output_offset=0;for(unsigned i=6;i<14;i++)bili_audio_remote_state[i]=0;bili_audio_remote_state[13]=2166136261u;++bili_audio_remote_state[14];return 0;
}
int bili_audio_remote_finish(void)
{
    if(!job||bili_audio_remote_state[12])return 0;
    int e=job_call(H1NET_AUDIO_FINISH);if(!e)bili_audio_remote_state[12]=1;return e;
}
int bili_audio_remote_eof(void)
{
    if(!job)return 1;uint8_t p[4],reply[32];unsigned used=0;h1net_put32(p,job);
    int e=call(H1NET_AUDIO_INFO,p,4,reply,32,&used);if(e)return e;
    if(used!=32||h1net_u32(reply)!=job||h1net_u32(reply+8)!=32768||h1net_u32(reply+12)!=1)return -3;
    unsigned state=h1net_u32(reply+4),buffered=h1net_u32(reply+24);
    if(state==3)return -5;return state==2&&!buffered;
}
