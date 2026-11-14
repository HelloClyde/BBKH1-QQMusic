/* Real QQ network.c + H1NET client/server; synthetic delayed CDN boundary.
 * The clock and transport are deterministic model inputs, not physical USB. */
#include "app.h"
#include "h1net_server.h"
#include "transport.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
volatile uint32_t qm_state[24];
qm_player_state qm_play;
static h1net_server server;
static h1net_parser parser;
static unsigned clock_ms,usb_epoch=1,pumps,opens,max_live,busy_next;
static unsigned reply_size,reply_at;
static uint8_t reply[528];
static struct {unsigned live,start,length,used,ready;} jobs[4];
static unsigned live_count(void){unsigned n=0;for(unsigned i=0;i<4;i++)n+=jobs[i].live;return n;}
uint32_t qm_time(void){return clock_ms;}
void qm_idle(void *p){(void)p;clock_ms+=25;}
void qm_player_network_idle(void){pumps++;}
void qm_player_step(void){}
int qm_account_authorize(const char *url,const char *headers,const void *body,unsigned n,char **h,char **b,unsigned *length)
{(void)url;(void)headers;(void)body;*h=*b=NULL;*length=n;return 0;}
static uint16_t reset(void *p){(void)p;memset(jobs,0,sizeof jobs);return 0;}
static void capabilities(void *p,uint32_t out[4])
{(void)p;uint32_t words[4]={1,4,8192,H1NET_CAP_RELEASE|H1NET_CAP_HTTP_REQUEST};memcpy(out,words,sizeof words);}
static uint16_t range_open(void *p,const char *url,const h1net_range *r,uint32_t *id)
{
    (void)p;CHECK(!strcmp(url,"https://example.com/fixture.m4a"));
    if(r->offset>=1048576&&busy_next){busy_next--;return H1NET_BUSY;}
    for(unsigned i=0;i<4;i++)if(!jobs[i].live){
        jobs[i].live=1;jobs[i].start=r->offset;jobs[i].length=r->length;
        jobs[i].used=0;jobs[i].ready=clock_ms+700;*id=i+1;opens++;
        unsigned n=live_count();if(n>max_live)max_live=n;return 0;
    }return H1NET_BUSY;
}
static uint16_t info(void *p,uint32_t id,h1net_info *out)
{
    (void)p;if(!id||id>4||!jobs[id-1].live)return H1NET_BAD_JOB;
    unsigned i=id-1,buffered=0,ready=clock_ms>=jobs[i].ready;
    if(ready){buffered=jobs[i].length-jobs[i].used;if(buffered>8192)buffered=8192;}
    unsigned received=jobs[i].used+buffered;
    h1net_info v={id,!ready?H1NET_CONNECTING:received==jobs[i].length?H1NET_DONE:H1NET_RECEIVING,
        ready?206:0,ready?jobs[i].length:0xffffffffu,received,jobs[i].used,buffered,0};*out=v;return 0;
}
static uint16_t read_body(void *p,uint32_t id,unsigned want,uint8_t *out,uint32_t *offset,unsigned *n)
{
    (void)p;if(!id||id>4||!jobs[id-1].live)return H1NET_BAD_JOB;unsigned i=id-1;
    CHECK(clock_ms>=jobs[i].ready);*offset=jobs[i].used;*n=jobs[i].length-jobs[i].used;if(*n>want)*n=want;
    for(unsigned j=0;j<*n;j++)out[j]=(uint8_t)((jobs[i].start+jobs[i].used+j)%251);
    jobs[i].used+=*n;return 0;
}
static uint16_t release_job(void *p,uint32_t id)
{(void)p;if(!id||id>4||!jobs[id-1].live)return H1NET_BAD_JOB;jobs[id-1].live=0;return 0;}
static void frame(void *p,const h1net_frame *f)
{(void)p;CHECK(reply_at==reply_size);reply_size=(unsigned)h1net_server_dispatch(&server,f,reply,sizeof reply);reply_at=0;}
int h1net_transport_open_attached(void){return 0;}
void h1net_transport_poll(void){}
int h1net_transport_connected(void){return 1;}
uint32_t h1net_transport_epoch(void){return usb_epoch;}
void h1net_transport_bind(void){reply_size=reply_at=0;h1net_parser_init(&parser);}
void h1net_transport_close(void){}
int h1net_transport_write(void *p,const uint8_t *data,unsigned n)
{(void)p;if(n>64)n=64;h1net_parser_feed(&parser,data,n,frame,0);return (int)n;}
int h1net_transport_finish(void *p){(void)p;return 1;}
int h1net_transport_read(void *p,uint8_t *data,unsigned n)
{(void)p;unsigned count=reply_size-reply_at;if(count>n)count=n;memcpy(data,reply+reply_at,count);reply_at+=count;return (int)count;}
static void verify(unsigned start,const uint8_t *out,unsigned n)
{for(unsigned i=0;i<n;i++)CHECK(out[i]==(start+i)%251);}
int main(int argc,char **argv)
{
    CHECK(argc==2);int expect=atoi(argv[1]);h1net_backend b={0};
    b.reset=reset;b.capabilities=capabilities;b.range=range_open;b.info=info;b.read=read_body;b.release=release_job;
    h1net_server_init(&server,&b);h1net_transport_bind();
    const char *url="https://example.com/fixture.m4a";uint8_t data[4096];unsigned waits[2]={0},total=2*1048576+8192;
    for(unsigned at=0;at<total;at+=sizeof data){
        unsigned before=clock_ms;CHECK(!qm_net_stream(url,at,sizeof data,total,data));verify(at,data,sizeof data);
        if(at==1048576)waits[0]=clock_ms-before;if(at==2*1048576)waits[1]=clock_ms-before;
        /* 96 kbit/s consumption. A 4 KiB cache is about 341ms of media. */
        clock_ms+=341;
    }
    qm_net_stream_close();CHECK(live_count()==0&&pumps>0);
    if(expect){CHECK(waits[0]<256&&waits[1]<256&&max_live==2);}
    else CHECK(waits[0]>=700&&waits[1]>=700&&max_live==1);
    /* Seek with current + ahead active must cancel both, then return exact bytes. */
    CHECK(!qm_net_stream(url,0,4096,total,data));clock_ms+=3000;
    for(unsigned at=4096;at<1048576-32768;at+=4096){CHECK(!qm_net_stream(url,at,4096,total,data));clock_ms+=341;}
    CHECK(live_count()==(expect?2u:1u));
    CHECK(!qm_net_stream(url,65536,4096,total,data));verify(65536,data,sizeof data);
    qm_net_stream_close();CHECK(!live_count());
    /* Explicit exit while the speculative task is still live. */
    for(unsigned at=0;at<1048576-32768;at+=4096){CHECK(!qm_net_stream(url,at,4096,total,data));clock_ms+=341;}
    CHECK(live_count()==(expect?2u:1u));qm_net_stream_close();CHECK(!live_count());
    /* A BUSY speculative open is optional, not a failure of current playback. */
    busy_next=(unsigned)expect;
    CHECK(!qm_net_stream(url,0,4096,total,data));
    for(unsigned at=4096;at<=1048576;at+=4096){CHECK(!qm_net_stream(url,at,4096,total,data));verify(at,data,sizeof data);clock_ms+=341;}
    qm_net_stream_close();CHECK(!live_count());
    printf("{\"passed\":true,\"prefetch\":%s,\"boundary_wait_ms\":[%u,%u],\"max_jobs\":%u,\"range_opens\":%u,\"pcm_pump_opportunities\":%u}\n",
           expect?"true":"false",waits[0],waits[1],max_live,opens,pumps);
    return 0;
}
