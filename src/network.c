/* QQ metadata and original M4A ranges use only the generic H1NET transport. */
#include "app.h"
#include "h1_sdk.h"
#include "transport.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
static h1net_client client;
static uint32_t epoch;
static h1net_rpc_task probe;
static unsigned probe_phase;
static uint32_t next_probe;
unsigned qm_connection_status;
int qm_cancelled;
static uint32_t now(void *p){(void)p;return qm_time();}
static int link(void)
{
    h1net_transport_poll();if(!h1net_transport_connected())return H1NET_IO;
    if(!client.ready||client.broken||epoch!=h1net_transport_epoch()){
        epoch=h1net_transport_epoch();h1net_transport_bind();h1net_io io={NULL,h1net_transport_write,h1net_transport_read,h1net_transport_finish,qm_idle,now};
        h1net_client_init(&client,&io,5000);int e=h1net_hello(&client);if(!e)e=h1net_capabilities(&client);
        if(!e&&(client.features&(H1NET_CAP_RELEASE|H1NET_CAP_HTTP_REQUEST))!=(H1NET_CAP_RELEASE|H1NET_CAP_HTTP_REQUEST))e=H1NET_PROTOCOL;
        if(e){client.ready=0;return e;}
    }return 0;
}
int qm_net_open(void){return h1net_transport_open_attached();}
void qm_net_reset(void){client.ready=0;}
int qm_net_probe_active(void){return probe_phase!=0;}
static void probe_failed(void)
{
    probe_phase=0;client.ready=0;client.broken=1;client.pending_rpc=0;
    client.rpc_timeout_ms=5000;next_probe=qm_time()+3000;
    qm_connection_status=QM_DEVICE_ERROR;
}
void qm_net_probe_step(int idle)
{
    if(!h1net_transport_connected()){
        if(probe_phase){client.pending_rpc=0;client.broken=1;probe_phase=0;}
        qm_connection_status=QM_DEVICE_WAIT;next_probe=0;return;
    }
    if(!probe_phase){
        if(!idle||(int32_t)(qm_time()-next_probe)<0)return;
        if(!client.ready||client.broken||epoch!=h1net_transport_epoch()){
            epoch=h1net_transport_epoch();h1net_transport_bind();
            h1net_io io={NULL,h1net_transport_write,h1net_transport_read,h1net_transport_finish,qm_idle,now};
            h1net_client_init(&client,&io,1000);probe_phase=1;
            qm_connection_status=QM_DEVICE_CHECKING;
        }else {probe_phase=3;client.rpc_timeout_ms=1000;}
        unsigned op=probe_phase==1?H1NET_HELLO:H1NET_STATUS;
        if(h1net_rpc_begin(&client,&probe,(uint8_t)op,NULL,0)){probe_failed();return;}
    }
    for(unsigned work=0;work<8&&probe_phase;work++){
        int result=h1net_rpc_poll(&client,&probe);
        if(!result)return;
        if(result<0){probe_failed();return;}
        if(probe_phase==1){
            static const char identity[]=H1NET_IDENTITY;
            if(client.response_length!=sizeof identity-1||memcmp(client.response,identity,sizeof identity-1)){probe_failed();return;}
            client.ready=1;probe_phase=2;
        }else if(probe_phase==2){
            if(client.response_length!=16||h1net_u32(client.response)!=1){probe_failed();return;}
            client.max_jobs=h1net_u32(client.response+4);client.features=h1net_u32(client.response+12);
            if((client.features&(H1NET_CAP_RELEASE|H1NET_CAP_HTTP_REQUEST))!=(H1NET_CAP_RELEASE|H1NET_CAP_HTTP_REQUEST)){probe_failed();return;}
            probe_phase=3;
        }else {
            if(client.response_length!=24){probe_failed();return;}
            qm_connection_status=h1net_u32(client.response+4)?QM_NETWORK_READY:QM_WIFI_OFFLINE;
            probe_phase=0;client.rpc_timeout_ms=5000;next_probe=qm_time()+1000;return;
        }
        if(h1net_rpc_begin(&client,&probe,probe_phase==2?H1NET_CAPABILITIES:H1NET_STATUS,NULL,0)){probe_failed();return;}
    }
}
uint32_t qm_net_features(void){return link()?0:client.features;}
int qm_net_compute_rpc(unsigned op,const void *data,unsigned length,void *out,unsigned cap,unsigned *n)
{
    if(op<H1NET_AUDIO_OPEN||op>H1NET_AUDIO_FINISH)return H1NET_PROTOCOL;
    int e=link();if(!e)e=h1net_rpc(&client,(uint8_t)op,data,length,out,cap,n);
    return e==H1NET_REMOTE?-100-(int)client.remote_status:e;
}
static void release(uint32_t job)
{if(job&&!client.broken&&h1net_transport_connected()&&epoch==h1net_transport_epoch())(void)h1net_http_release(&client,job);}
static int open_request(const char *url,const char *method,const char *body,unsigned maximum,uint32_t *job)
{
    int e=link();if(e)return e;
    static const char headers[]="Referer: https://y.qq.com/\r\nContent-Type: application/json; charset=utf-8";
    char *private_headers=NULL,*private_body=NULL;unsigned length=body?(unsigned)strlen(body):0;
    if(qm_account_authorize(url,headers,body,length,&private_headers,&private_body,&length)<0)return H1NET_SINK;
    const char *send_headers=private_headers?private_headers:headers,*send_body=private_body?private_body:body;
    qm_state[7]++;e=h1net_http_request_open(&client,url,method,send_headers,send_body,length,maximum,60000,job);
    if(e==H1NET_REMOTE&&client.remote_status==H1NET_NOT_CONNECTED){
        client.ready=0;e=link();
        if(!e)e=h1net_http_request_open(&client,url,method,send_headers,send_body,length,maximum,60000,job);
    }
    if(private_headers){h1net_secure_clear(private_headers,strlen(private_headers));free(private_headers);}
    if(private_body){h1net_secure_clear(private_body,length);free(private_body);}
    return e;
}
/* Generic response access for application-owned OAuth/cookies. No redirect is
 * followed. Callers own all returned storage, including sensitive headers. */
int qm_net_request(const char *url,const char *method,const char *headers,const char *body,unsigned maximum,unsigned timeout,
                   char **out,unsigned *length,char **fields,unsigned *status)
{
    *out=*fields=NULL;*length=*status=0;int e=link();uint32_t job=0;
    if(!e&&!(client.features&H1NET_CAP_HTTP_HEADERS))e=H1NET_PROTOCOL;
    if(!e)e=h1net_http_request_open(&client,url,method,headers,body,body?(unsigned)strlen(body):0,maximum,timeout,&job);
    char *data=NULL,*raw=NULL;unsigned used=0,cap=0;uint32_t progress=qm_time();
    while(!e&&!qm_cancelled){
        h1net_info info;e=h1net_http_info(&client,job,&info);if(e)break;*status=info.http_status;
        if(info.state==H1NET_FAILED||info.state==H1NET_CANCELLED){e=H1NET_IO;break;}
        if(info.delivered!=used||info.received>maximum){e=H1NET_PROTOCOL;break;}
        if(info.buffered){unsigned n=info.buffered;if(n>500)n=500;
            if(n>maximum-used){e=H1NET_PROTOCOL;break;}
            if(used+n+1>cap){unsigned next=cap?cap*2:4096;while(next<used+n+1)next*=2;if(next>maximum+1)next=maximum+1;
                char *copy=realloc(data,next);if(!copy){e=H1NET_SINK;break;}data=copy;cap=next;}
            unsigned got=0;e=h1net_http_read(&client,job,used,(uint8_t *)data+used,n,&got);if(e)break;
            if(!got){e=H1NET_PROTOCOL;break;}used+=got;progress=qm_time();
        }else if(info.state==H1NET_DONE){if(info.content_length!=0xffffffffu&&used!=info.content_length)e=H1NET_PROTOCOL;break;}
        else {if(qm_time()-progress>=timeout+1000u){e=H1NET_TIMEOUT;break;}qm_idle(NULL);}
        /* The response has been copied into local storage and no RPC owns the
         * client. A complete player step may use its own range/AAC jobs here. */
        if(!e&&!qm_cancelled&&qm_play.playing)qm_player_step();
    }
    unsigned offset=0,total=0;
    if(!e&&!qm_cancelled){
        do {uint8_t request[12],response[512];unsigned n=0;
            h1net_put32(request,job);h1net_put32(request+4,offset);h1net_put32(request+8,500);
            e=h1net_rpc(&client,H1NET_HTTP_HEADERS,request,12,response,sizeof response,&n);
            if(e)break;
            unsigned size=n>=12?h1net_u32(response+8):0;
            if(n<12||h1net_u32(response)!=job||h1net_u32(response+4)!=offset||size>8192||offset>size||n-12>size-offset||
                (offset&&size!=total)||(size>offset&&n==12)){e=H1NET_PROTOCOL;break;}
            if(!raw){total=size;raw=calloc(1,total+1);if(!raw){e=H1NET_SINK;break;}}
            memcpy(raw+offset,response+12,n-12);offset+=n-12;h1net_secure_clear(response,sizeof response);
            if(!qm_cancelled&&qm_play.playing)qm_player_step();
        }while(offset<total&&!qm_cancelled);
    }
    if(qm_cancelled)e=H1NET_ABORTED;release(job);
    if(e){if(data){h1net_secure_clear(data,used);free(data);}if(raw){h1net_secure_clear(raw,total);free(raw);}return e;}
    if(!data)data=malloc(1);if(!data){if(raw){h1net_secure_clear(raw,total);free(raw);}return H1NET_SINK;}
    data[used]=0;*out=data;*length=used;*fields=raw;return 0;
}
int qm_net_fetch(const char *url,const char *method,const char *body,unsigned maximum,char **out,size_t *length)
{
    *out=NULL;*length=0;if(!maximum||maximum>384u*1024u)return H1NET_PROTOCOL;
    uint32_t job=0;int e=open_request(url,method,body,maximum,&job);char *data=NULL;unsigned used=0,cap=0;uint32_t progress=qm_time();
    while(!e&&!qm_cancelled){
        h1net_info info;e=h1net_http_info(&client,job,&info);if(e)break;qm_state[9]=info.http_status;
        if(info.state==H1NET_FAILED||info.state==H1NET_CANCELLED){e=H1NET_IO;break;}
        if(info.http_status&&info.http_status!=200){e=-(int)info.http_status;break;}
        if(info.delivered!=used||info.received>maximum){e=H1NET_PROTOCOL;break;}
        if(info.buffered){
            unsigned n=info.buffered;if(n>500)n=500;
            if(n>maximum-used){e=H1NET_PROTOCOL;break;}
            if(used+n+1>cap){unsigned next=cap?cap*2:4096;while(next<used+n+1)next*=2;if(next>maximum+1)next=maximum+1;char *v=realloc(data,next);if(!v){e=H1NET_SINK;break;}data=v;cap=next;}
            unsigned got=0;e=h1net_http_read(&client,job,used,(uint8_t *)data+used,n,&got);if(e)break;
            if(!got){e=H1NET_PROTOCOL;break;}used+=got;qm_state[8]+=got;progress=qm_time();
        }else if(info.state==H1NET_DONE){if(info.content_length!=0xffffffffu&&used!=info.content_length)e=H1NET_PROTOCOL;break;}
        else {if(qm_time()-progress>=60000u){e=H1NET_TIMEOUT;break;}qm_idle(NULL);}
        if(!e&&!qm_cancelled&&qm_play.playing)qm_player_step();
    }
    if(qm_cancelled)e=H1NET_ABORTED;release(job);qm_state[10]=(uint32_t)e;
    if(e)free(data);else{if(!data)data=malloc(1);if(!data)return H1NET_SINK;data[used]=0;*out=data;*length=used;}return e;
}
int qm_net_size(const char *url,uint32_t *size)
{
    *size=0;uint32_t job=0;int e=open_request(url,"GET",NULL,H1NET_MAX_DOWNLOAD,&job);uint32_t start=qm_time();
    while(!e&&!qm_cancelled){h1net_info info;e=h1net_http_info(&client,job,&info);if(e)break;qm_state[9]=info.http_status;
        if(info.state==H1NET_FAILED||info.state==H1NET_CANCELLED){e=H1NET_IO;break;}
        if(info.http_status&&info.http_status!=200){e=-(int)info.http_status;break;}
        if(info.http_status==200&&info.content_length!=0xffffffffu){if(!info.content_length||info.content_length>H1NET_MAX_DOWNLOAD)e=H1NET_PROTOCOL;else *size=info.content_length;break;}
        if(qm_time()-start>=15000){e=H1NET_TIMEOUT;break;}qm_idle(NULL);
    }
    if(qm_cancelled)e=H1NET_ABORTED;release(job);return e;
}
typedef struct {uint32_t job,start,length,used,epoch,total;char url[401];} music_stream;
static music_stream stream,ahead;
static uint32_t prefetch_retry;
/* Retained counters only: magic/schema, demand opens, ahead opens/promotions,
 * optional-open failures, max/last read ms, last offset, HTTP/backend/RPC error,
 * max promotion-read ms, active/ahead job and bytes read. No URLs/credentials. */
volatile uint32_t qm_stream_diag[16]={0x31534d51u,1};
static void stream_drop(music_stream *s)
{if(s->epoch==epoch)release(s->job);memset(s,0,sizeof *s);}
void qm_net_stream_close(void)
{stream_drop(&stream);stream_drop(&ahead);prefetch_retry=0;qm_stream_diag[13]=qm_stream_diag[14]=0;}
static int stream_match(const music_stream *s,const char *url,uint32_t offset,uint32_t total)
{return s->job&&s->epoch==epoch&&s->total==total&&!strcmp(s->url,url)&&offset==s->start+s->used;}
static int stream_open(music_stream *s,const char *url,uint32_t offset,uint32_t total)
{
    uint32_t length=total-offset;if(length>1024*1024)length=1024*1024;
    h1net_range range={offset,length,total,60000,"https://y.qq.com/"};
    int e=h1net_http_range_open(&client,url,&range,&s->job);if(e)return e;
    s->start=offset;s->length=length;s->used=0;s->epoch=epoch;s->total=total;
    memcpy(s->url,url,strlen(url)+1);qm_state[7]++;return 0;
}
static int stream_prefetch(const char *url,uint32_t total)
{
    /* Begin the NEXT HTTPS task while 32 KiB of the current range remain.
     * A 96 kbit/s track has ~2.7 s of compressed audio here; waiting until the
     * 1 MiB boundary leaves only the native 256 ms PCM ring to hide TLS setup.
     * Worker buffering is still bounded to 8 KiB; no extra H1 bulk cache. */
    if(ahead.job||!stream.job||stream.length-stream.used>32768||stream.start+stream.length>=total||
       (int32_t)(qm_time()-prefetch_retry)<0)return 0;
    int e=stream_open(&ahead,url,stream.start+stream.length,total);
    if(!e){qm_stream_diag[3]++;qm_stream_diag[14]=ahead.job;return 0;}
    qm_stream_diag[5]++;prefetch_retry=qm_time()+250;
    /* A speculative BUSY/rejection must not discard playable current bytes.
     * Transport/protocol failures remain fatal: never hide a broken session. */
    return e==H1NET_REMOTE?0:e;
}
int qm_net_stream(const char *url,uint32_t offset,uint32_t n,uint32_t total,uint8_t *out)
{
    if(!url||strlen(url)>400||!out||!n||n>32768||offset>=total||n>total-offset)return H1NET_PROTOCOL;
    int e=link();unsigned used=0,promoted=0;if(e)return e;
    if(stream.job&&stream.epoch!=epoch)memset(&stream,0,sizeof stream);
    if(ahead.job&&ahead.epoch!=epoch)memset(&ahead,0,sizeof ahead);
    if(stream.job&&!stream_match(&stream,url,offset,total))qm_net_stream_close();
    if(!stream.job&&ahead.job&&!stream_match(&ahead,url,offset,total))qm_net_stream_close();
    uint32_t started=qm_time(),progress=started;
    while(used<n&&!qm_cancelled){
        if(!stream.job){
            if(stream_match(&ahead,url,offset+used,total)){
                stream=ahead;memset(&ahead,0,sizeof ahead);promoted=1;qm_stream_diag[4]++;qm_stream_diag[14]=0;
            }else {e=stream_open(&stream,url,offset+used,total);if(e)break;qm_stream_diag[2]++;}
            qm_stream_diag[13]=stream.job;
        }
        h1net_info info;e=h1net_http_info(&client,stream.job,&info);if(e)break;qm_state[9]=info.http_status;
        qm_stream_diag[9]=info.http_status;qm_stream_diag[10]=info.error;
        qm_player_network_idle();
        if(info.delivered!=stream.used||info.received>stream.length||(info.http_status&&info.http_status!=206)||
           ((info.http_status==206||info.state==H1NET_DONE)&&info.content_length!=0xffffffffu&&info.content_length!=stream.length)||
           (info.state==H1NET_DONE&&info.received!=stream.length)){e=H1NET_PROTOCOL;break;}
        if(info.state==H1NET_FAILED||info.state==H1NET_CANCELLED){e=H1NET_IO;break;}
        if(info.buffered){unsigned available=info.buffered;
            while(available&&used<n){unsigned want=n-used;if(want>available)want=available;if(want>500)want=500;unsigned got=0;
                e=h1net_http_read(&client,stream.job,stream.used,out+used,want,&got);if(e)break;if(!got){e=H1NET_PROTOCOL;break;}
                stream.used+=got;used+=got;available-=got;qm_state[8]+=got;progress=qm_time();
                qm_player_network_idle();}if(e)break;
        }else {if(info.state==H1NET_DONE){e=H1NET_PROTOCOL;break;}if(qm_time()-progress>=15000){e=H1NET_TIMEOUT;break;}qm_idle(NULL);}
        if(!e){e=stream_prefetch(url,total);if(e)break;}
        if(stream.job&&stream.used==stream.length){stream_drop(&stream);qm_stream_diag[13]=0;}
    }
    if(qm_cancelled)e=H1NET_ABORTED;
    if(e)qm_net_stream_close();qm_state[10]=(uint32_t)e;
    uint32_t elapsed=qm_time()-started;qm_stream_diag[7]=elapsed;qm_stream_diag[8]=offset;qm_stream_diag[11]=(uint32_t)e;
    if(elapsed>qm_stream_diag[6])qm_stream_diag[6]=elapsed;
    if(promoted&&elapsed>qm_stream_diag[12])qm_stream_diag[12]=elapsed;
    qm_stream_diag[15]+=used;return e?e:used==n?0:H1NET_PROTOCOL;
}
void qm_net_close(void){qm_net_stream_close();h1net_transport_close();client.ready=0;client.pending_rpc=0;probe_phase=0;next_probe=0;qm_connection_status=QM_DEVICE_WAIT;}
