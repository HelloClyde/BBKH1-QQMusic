#include "transport.h"
#ifdef H1NET_DEBUG_TRANSPORT
/* Foreground-BDA-owned mailbox. H1Debug remains the sole USB controller owner.
 * Host must verify the loaded BDA bytes, build ID, magic and schema before writing. */
typedef struct {
    uint32_t header[16],info[8];
    char path[32],preview[68];
    uint32_t url_length;
    char url[404];
    uint8_t tx[H1NET_MAX_FRAME],rx[H1NET_MAX_FRAME];
} debug_mailbox;
typedef char check_mailbox_size[(sizeof(debug_mailbox)==1660)?1:-1];
volatile debug_mailbox h1net_debug_mailbox;
static uint32_t request_used,applied_url;
#define BOX h1net_debug_mailbox
#define BARRIER() __asm__ volatile("":::"memory")
int h1net_transport_open(void)
{
    BOX.header[0]=0x31445748u;BOX.header[1]=1;BOX.header[2]=sizeof BOX;
    BOX.header[3]=H1NET_DBG_BUILD_ID;BOX.header[4]=1;return 0;
}
void h1net_transport_close(void){BOX.header[10]=0;BOX.header[4]=0;}
int h1net_transport_open_attached(void){return h1net_transport_open();}
void h1net_transport_poll(void){}
int h1net_transport_needs_unplug(void){return 0;}
int h1net_transport_faulted(void){return 0;}
int h1net_transport_connected(void){return BOX.header[4] && BOX.header[10]!=0;}
uint32_t h1net_transport_epoch(void){return BOX.header[10];}
void h1net_transport_bind(void){request_used=0;BOX.header[5]=BOX.header[7]=0;}
int h1net_transport_write(void *unused,const uint8_t *data,unsigned n)
{
    (void)unused;if(!h1net_transport_connected())return -1;
    if(BOX.header[5])return 0;
    if(n>H1NET_MAX_FRAME-request_used)return -1;
    for(unsigned i=0;i<n;++i)BOX.tx[request_used+i]=data[i];request_used+=n;return (int)n;
}
int h1net_transport_finish(void *unused)
{
    (void)unused;if(!h1net_transport_connected())return -1;
    if(!request_used || BOX.header[5])return -1;
    BOX.header[6]=request_used;request_used=0;BARRIER();BOX.header[5]=1;return 1;
}
int h1net_transport_read(void *unused,uint8_t *data,unsigned n)
{
    (void)unused;if(!h1net_transport_connected())return -1;if(!BOX.header[7])return 0;
    uint32_t length=BOX.header[8],offset=BOX.header[9];
    if(length>H1NET_MAX_FRAME || offset>length)return -1;
    if(n>length-offset)n=length-offset;
    for(unsigned i=0;i<n;++i)data[i]=BOX.rx[offset+i];
    BOX.header[9]=offset+n;BARRIER();if(offset+n==length)BOX.header[7]=0;return (int)n;
}
int h1net_transport_url(char *out,unsigned capacity)
{
    uint32_t sequence=BOX.header[15];if(sequence==applied_url)return 0;
    uint32_t n=BOX.url_length;applied_url=sequence;
    if(n>=capacity || n>H1NET_MAX_URL)return 0;
    for(unsigned i=0;i<n;++i)out[i]=BOX.url[i];out[n]=0;
    return h1net_valid_url((const uint8_t *)out,n);
}
void h1net_transport_begin(void)
{BOX.header[14]=0;BOX.header[13]=0;++BOX.header[11];}
void h1net_transport_result(int error,int good,const h1net_info *info,const char *path,const char *preview)
{
    const uint32_t values[8]={info->job,info->state,info->http_status,info->content_length,
                            info->received,info->delivered,info->buffered,info->error};
    for(unsigned i=0;i<8;++i)BOX.info[i]=values[i];
    unsigned i=0;for(;path[i] && i<31;++i)BOX.path[i]=path[i];BOX.path[i]=0;
    for(i=0;preview[i] && i<67;++i)BOX.preview[i]=preview[i];BOX.preview[i]=0;
    BOX.header[13]=(uint32_t)error;BOX.header[14]=(uint32_t)good;BARRIER();BOX.header[12]=BOX.header[11];
}
#else
#include "usb.h"
static debug_usb usb;
static uint32_t frame_bytes,bound_epoch;
static int zlp_sent;
int h1net_transport_open(void){return debug_usb_open(&usb);}
int h1net_transport_open_attached(void){return debug_usb_open_attached(&usb);}
void h1net_transport_close(void){debug_usb_close(&usb);}
void h1net_transport_poll(void){debug_usb_poll(&usb);}
int h1net_transport_needs_unplug(void){return debug_usb_cable_connected();}
int h1net_transport_faulted(void){return usb.owned && usb.ownership_fault;}
int h1net_transport_connected(void)
{return !usb.ownership_fault && usb.configured && (usb.control_lines&1u);}
uint32_t h1net_transport_epoch(void){return usb.session_epoch;}
void h1net_transport_bind(void){bound_epoch=usb.session_epoch;frame_bytes=0;zlp_sent=0;}
static int live(void){return h1net_transport_connected() && usb.session_epoch==bound_epoch;}
int h1net_transport_write(void *unused,const uint8_t *data,unsigned n)
{
    (void)unused;debug_usb_poll(&usb);if(!live())return -1;if(n>64)n=64;
    if(!debug_usb_write(&usb,data,n))return 0;frame_bytes+=n;return (int)n;
}
int h1net_transport_read(void *unused,uint8_t *data,unsigned n)
{(void)unused;debug_usb_poll(&usb);return live()?debug_usb_read(&usb,data,n):-1;}
int h1net_transport_finish(void *unused)
{
    (void)unused;debug_usb_poll(&usb);if(!live())return -1;
    if(!debug_usb_tx_idle(&usb))return 0;
    if(frame_bytes && !(frame_bytes%64) && !zlp_sent){
        if(!debug_usb_write(&usb,NULL,0))return 0;zlp_sent=1;return 0;
    }
    frame_bytes=0;zlp_sent=0;return 1;
}
int h1net_transport_url(char *out,unsigned capacity){(void)out;(void)capacity;return 0;}
void h1net_transport_begin(void){}
void h1net_transport_result(int error,int good,const h1net_info *info,const char *path,const char *preview)
{(void)error;(void)good;(void)info;(void)path;(void)preview;}
#endif
