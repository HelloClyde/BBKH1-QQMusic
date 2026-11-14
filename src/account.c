/* Application-owned QQ / WeChat login. ESP remains a generic HTTP/AAC peripheral.
 * Wire protocol reference: L-1124/QQMusicApi modules/login.py (see THIRD_PARTY.md). */
#include "app.h"
#include "h1_sdk.h"
#include "h1net_wire.h"
#include "platform/images.h"
#include "../third_party/cjson/cJSON.h"
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>
#define QR_LIMIT (96u*1024u)
#define CREDENTIAL_LIMIT 8192u
#define AUTH_IDLE QM_AUTH_IDLE
#define AUTH_FETCHING QM_AUTH_FETCHING
#define AUTH_SCAN QM_AUTH_SCAN
#define AUTH_CONFIRM QM_AUTH_CONFIRM
#define AUTH_DONE QM_AUTH_DONE
#define AUTH_EXPIRED QM_AUTH_EXPIRED
#define AUTH_ERROR QM_AUTH_ERROR
#define AUTH_RESTORE QM_AUTH_RESTORE
qm_account_state qm_account;
unsigned qm_account_revision;
uint16_t *qm_account_qr;
unsigned qm_account_qr_width,qm_account_qr_height;
#define state qm_account.state
#define kind qm_account.kind
#define error_code qm_account.error
#define logged qm_account.logged
#define nickname qm_account.nickname
#define message qm_account.message
static uint32_t session=1,next_poll,expires;
static char *credential;
static char login_identifier[256];
static int pending,cancelled,loaded;
static void take(void){}
static void give(void){}
static int current(uint32_t id){return id==session&&!cancelled&&!qm_cancelled;}
static void change(uint32_t id,unsigned value,const char *text)
{if(current(id)){state=value;snprintf(message,sizeof message,"%s",text);}}
static void erase_free(void *p,unsigned n){if(p){h1net_secure_clear(p,n);free(p);}}
static const char *string(cJSON *object,const char *name)
{cJSON *v=cJSON_GetObjectItemCaseSensitive(object,name);return cJSON_IsString(v)?v->valuestring:"";}
static uint32_t auth_random(void){static uint32_t sequence;sequence=sequence*1664525u+1013904223u+qm_time();return sequence;}
typedef struct {uint8_t *body;unsigned used;int status;char cookies[2048],location[2048];} auth_reply;
static uint32_t hash33(const char *s,uint32_t value)
{while(*s)value=value*33u+(unsigned char)*s++;return value&0x7fffffffu;}
static int cookie_get(const char *jar,const char *name,char *out,unsigned cap)
{
    size_t n=strlen(name);
    for(const char *p=jar;*p;){
        const char *end=strchr(p,';');if(!end)end=p+strlen(p);
        if((size_t)(end-p)>n&&p[n]=='='&&!memcmp(p,name,n)){
            size_t length=(size_t)(end-p)-n-1;if(length>=cap)return 0;
            memcpy(out,p+n+1,length);out[length]=0;return length!=0;
        }
        p=*end?end+1:end;while(*p==' ')p++;
    }
    return 0;
}
static int cookie_set(char jar[2048],const char *value)
{
    const char *equal=strchr(value,'='),*end=strchr(value,';');
    if(!end)end=value+strlen(value);
    if(!equal||equal==value||equal>=end)return 0;
    unsigned name=(unsigned)(equal-value),length=(unsigned)(end-value);
    for(unsigned i=0;i<length;i++)if((unsigned char)value[i]<32||(unsigned char)value[i]>126)return 0;
    for(char *p=jar;*p;){
        char *next=strchr(p,';');if(!next)next=p+strlen(p);
        if((unsigned)(next-p)>name&&p[name]=='='&&!memcmp(p,value,name)){
            char *after=*next?next+1:next;while(*after==' ')after++;
            memmove(p,after,strlen(after)+1);break;
        }
        p=*next?next+1:next;while(*p==' ')p++;
    }
    unsigned used=(unsigned)strlen(jar);
    if(used&&used>=2&&!strcmp(jar+used-2,"; ")){used-=2;jar[used]=0;}
    if(used+length+(used?2:0)>=2048)return 0;
    if(used){jar[used++]=';';jar[used++]=' ';}
    memcpy(jar+used,value,length);jar[used+length]=0;return 1;
}
static void reply_free(auth_reply *r)
{if(r){erase_free(r->body,r->used);h1net_secure_clear(r,sizeof *r);free(r);}}
static auth_reply *http(uint32_t id,const char *url,const char *body,const char *content_type,const char *cookies,unsigned limit)
{
    if(!current(id))return NULL;
    auth_reply *r=calloc(1,sizeof *r);char *fields=NULL;unsigned status=0;
    char headers[H1NET_MAX_HEADERS+1];
    int n=snprintf(headers,sizeof headers,"Referer: %s\r\nUser-Agent: Mozilla/5.0%s%s%s%s",
        strstr(url,"ptlogin2.")?"https://xui.ptlogin2.qq.com/":strstr(url,"weixin.qq.com/")?"https://open.weixin.qq.com/":"https://y.qq.com/",
        body?"\r\nContent-Type: ":"",body?content_type:"",cookies&&*cookies?"\r\nCookie: ":"",cookies&&*cookies?cookies:"");
    if(!r||n<0||(unsigned)n>=sizeof headers){reply_free(r);return NULL;}
    int e=qm_net_request(url,body?"POST":"GET",headers,body,limit,5000,(char **)&r->body,&r->used,&fields,&status);
    h1net_secure_clear(headers,sizeof headers);r->status=(int)status;
    if(e||!current(id)){if(fields)erase_free(fields,(unsigned)strlen(fields));reply_free(r);return NULL;}
    unsigned fields_size=fields?(unsigned)strlen(fields):0;bool ok=true;
    for(char *p=fields;p&&*p;){char *end=strstr(p,"\r\n"),*colon=strchr(p,':');if(!end||!colon||colon>=end){ok=false;break;}
        *end=0;*colon++=0;while(*colon==' '||*colon=='\t')colon++;
        if(!strcasecmp(p,"Set-Cookie")){if(!cookie_set(r->cookies,colon))ok=false;}
        else if(!strcasecmp(p,"Location")){if(strlen(colon)>=sizeof r->location)ok=false;else strcpy(r->location,colon);}
        p=end+2;
    }
    /* Header splitting introduced NULs: erase the full allocation length. */
    erase_free(fields,fields_size);
    if(!ok){reply_free(r);return NULL;}return r;
}
static int encode(char *out,unsigned cap,const char *value)
{
    static const char hex[]="0123456789ABCDEF";unsigned used=0;
    for(const unsigned char *p=(const unsigned char *)value;*p;p++){
        bool safe=(*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||strchr("-_.~",*p);
        if(used+(safe?1:3)>=cap)return 0;
        if(safe)out[used++]=(char)*p;else{out[used++]='%';out[used++]=hex[*p>>4];out[used++]=hex[*p&15];}
    }
    out[used]=0;return 1;
}
static int parameter(const char *url,const char *name,char *out,unsigned cap)
{
    unsigned n=(unsigned)strlen(name);
    for(const char *p=url;*p;p++)if((*p=='?'||*p=='&')&&!strncmp(p+1,name,n)&&p[n+1]=='='){
        const char *start=p+n+2,*end=strpbrk(start,"&#");if(!end)end=start+strlen(start);
        if((unsigned)(end-start)>=cap)return 0;memcpy(out,start,(size_t)(end-start));out[end-start]=0;return *out!=0;
    }
    return 0;
}
static char *credential_copy(void)
{take();char *copy=credential?strdup(credential):NULL;give();return copy;}
static int account_id(cJSON *c,char out[32])
{
    const char *s=string(c,"str_musicid");
    if(*s){if(strlen(s)>=32)return 0;strcpy(out,s);}
    else {
        cJSON *v=cJSON_GetObjectItemCaseSensitive(c,"musicid");
        if(cJSON_IsString(v)){if(strlen(v->valuestring)>=32)return 0;strcpy(out,v->valuestring);}
        else if(cJSON_IsNumber(v)&&v->valuedouble>0&&v->valuedouble<=9007199254740991.0)snprintf(out,32,"%.0f",v->valuedouble);
        else return 0;
    }
    for(unsigned i=0;out[i];i++)if(out[i]<'0'||out[i]>'9')return 0;
    return *out&&strcmp(out,"0");
}
static unsigned login_type(cJSON *c)
{cJSON *v=cJSON_GetObjectItemCaseSensitive(c,"loginType");return cJSON_IsNumber(v)?(unsigned)v->valueint:!strncmp(string(c,"musickey"),"W_X",3)?1:2;}
static int credential_cookie(cJSON *c,char out[1024],char id[32])
{
    const char *key=string(c,"musickey");if(!account_id(c,id)||!*key||strlen(key)>384)return 0;
    for(const char *p=key;*p;p++)if((unsigned char)*p<=32||*p==';'||(unsigned char)*p>=127)return 0;
    return snprintf(out,1024,"uin=%s;qqmusic_uin=%s;qm_keyst=%s;qqmusic_key=%s;tmeLoginType=%u",id,id,key,key,login_type(c))<1024;
}
static cJSON *cgi(uint32_t id,const char *module,const char *method,cJSON *param,unsigned type,cJSON *cred)
{
    cJSON *root=cJSON_CreateObject(),*comm=cJSON_AddObjectToObject(root,"comm"),*req=cJSON_AddObjectToObject(root,"req");
    if(!root||!comm||!req){cJSON_Delete(root);cJSON_Delete(param);return NULL;}
    cJSON_AddNumberToObject(comm,"ct",24);cJSON_AddNumberToObject(comm,"cv",0);
    cJSON_AddNumberToObject(comm,"tmeLoginType",type);cJSON_AddStringToObject(comm,"format","json");
    char cookie[1024]="",uin[32];
    if(cred&&credential_cookie(cred,cookie,uin)){cJSON_AddStringToObject(comm,"uin",uin);cJSON_AddStringToObject(comm,"authst",string(cred,"musickey"));}
    cJSON_AddStringToObject(req,"module",module);cJSON_AddStringToObject(req,"method",method);cJSON_AddItemToObject(req,"param",param);
    char *body=cJSON_PrintUnformatted(root);cJSON_Delete(root);
    auth_reply *r=body?http(id,"https://u.y.qq.com/cgi-bin/musicu.fcg",body,"application/json; charset=utf-8",cookie,65536):NULL;
    if(body)erase_free(body,(unsigned)strlen(body));h1net_secure_clear(cookie,sizeof cookie);
    cJSON *result=NULL;
    if(r&&r->status==200){cJSON *json=cJSON_Parse((const char *)r->body),*answer=cJSON_GetObjectItemCaseSensitive(json,"req");
        cJSON *code=cJSON_GetObjectItemCaseSensitive(answer,"code");
        if(cJSON_IsNumber(code)&&!code->valueint){
            cJSON *data=cJSON_GetObjectItemCaseSensitive(answer,"data"),*inner=cJSON_GetObjectItemCaseSensitive(data,"code");
            if(cJSON_IsNumber(inner)&&inner->valueint)error_code=(uint32_t)inner->valueint;
            else if(cJSON_IsObject(data))result=cJSON_Duplicate(data,true);
        }
        else if(cJSON_IsNumber(code)){take();error_code=(uint32_t)code->valueint;give();}
        cJSON_Delete(json);}
    reply_free(r);return result;
}
static const char *find_nick(cJSON *object,unsigned depth)
{
    if(!object||depth>8)return "";
    const char *s=string(object,"nickname");if(!*s)s=string(object,"nick");if(*s)return s;
    cJSON *child; cJSON_ArrayForEach(child,object){if(cJSON_IsObject(child)||cJSON_IsArray(child)){s=find_nick(child,depth+1);if(*s)return s;}}
    return "";
}
static int store(const char *text);
static int save_credential(uint32_t id,cJSON *data)
{
    char cookie[1024],uin[32];if(!data||!credential_cookie(data,cookie,uin))return 0;
    h1net_secure_clear(cookie,sizeof cookie);
    char *text=cJSON_PrintUnformatted(data);if(!text||strlen(text)>=CREDENTIAL_LIMIT){free(text);return 0;}
    if(!current(id)){erase_free(text,(unsigned)strlen(text));return 0;}
    if(!store(text)){
        error_code=3;state=AUTH_ERROR;snprintf(message,sizeof message,"保存登录失败，请检查H1存储空间");erase_free(text,(unsigned)strlen(text));return 0;}
    if(credential)erase_free(credential,(unsigned)strlen(credential));credential=text;logged=1;state=AUTH_DONE;error_code=0;qm_account_revision++;
    const char *nick=find_nick(data,0);snprintf(nickname,sizeof nickname,"%s",*nick?nick:login_type(data)==1?"微信账号":"QQ账号");
    snprintf(message,sizeof message,"已登录，重新打开时自动恢复");return 1;
}
static int quoted(const char *text,unsigned index,char *out,unsigned cap)
{
    const char *p=strchr(text,'(');if(!p)return 0;
    for(unsigned field=0;;field++){
        p=strchr(p,'\'');if(!p)return 0;p++;unsigned used=0;
        while(*p&&*p!='\''){
            if(*p=='\\'&&p[1])p++;
            if(field==index){if(used+1>=cap)return 0;out[used++]=*p;}p++;
        }
        if(!*p)return 0;
        if(field==index){out[used]=0;return 1;}p++;
    }
}
static cJSON *authorize_qq(uint32_t id,const char *redirect)
{
    char uin[32],sig[512],url[2048],skey[384],encoded[768];
    if(!parameter(redirect,"uin",uin,sizeof uin)||!parameter(redirect,"ptsigx",sig,sizeof sig))return NULL;
    snprintf(url,sizeof url,"https://ssl.ptlogin2.graph.qq.com/check_sig?uin=%s&pttype=1&service=ptqrlogin&nodirect=0&ptsigx=%s&s_url=https%%3A%%2F%%2Fgraph.qq.com%%2Foauth2.0%%2Flogin_jump&ptlang=2052&ptredirect=100&aid=716027609&daid=383&j_later=0&low_login_hour=0&regmaster=0&pt_login_type=3&pt_aid=0&pt_aaid=16&pt_light=0&pt_3rd_aid=100497308",uin,sig);
    auth_reply *check=http(id,url,NULL,NULL,NULL,32768);
    if(!check||!cookie_get(check->cookies,"p_skey",skey,sizeof skey)){reply_free(check);return NULL;}
    static const char redirect_uri[]="https://y.qq.com/portal/wx_redirect.html?login_type=1&surl=https://y.qq.com/";
    if(!encode(encoded,sizeof encoded,redirect_uri)){reply_free(check);return NULL;}
    char form[1600];
    snprintf(form,sizeof form,"response_type=code&client_id=100497308&redirect_uri=%s&scope=get_user_info%%2Cget_app_friends&state=state&switch=&from_ptlogin=1&src=1&update_auth=1&openapi=1010_1030&g_tk=%lu&auth_time=%llu&ui=%08lx-%04lx-4%03lx-a%03lx-%08lx%04lx",
        encoded,(unsigned long)hash33(skey,5381),(unsigned long long)time(NULL)*1000,
        (unsigned long)auth_random(),(unsigned long)(auth_random()&65535),(unsigned long)(auth_random()&4095),
        (unsigned long)(auth_random()&4095),(unsigned long)auth_random(),(unsigned long)(auth_random()&65535));
    h1net_secure_clear(skey,sizeof skey);
    auth_reply *answer=http(id,"https://graph.qq.com/oauth2.0/authorize",form,"application/x-www-form-urlencoded",check->cookies,32768);
    reply_free(check);h1net_secure_clear(form,sizeof form);
    char code[512];
    if(!answer||!parameter(answer->location,"code",code,sizeof code)){reply_free(answer);return NULL;}
    reply_free(answer);cJSON *param=cJSON_CreateObject();cJSON_AddStringToObject(param,"code",code);
    h1net_secure_clear(code,sizeof code);return cgi(id,"QQConnectLogin.LoginServer","QQLogin",param,2,NULL);
}
static int publish_qr(uint32_t id,auth_reply *r)
{
    if(!current(id)||!r||r->status!=200||!r->used||r->used>QR_LIMIT)return 0;
    uint16_t *image=NULL;unsigned w=0,h=0;
    if(qm_image_decode(r->body,r->used,&image,&w,&h,184,184))return 0;
    free(qm_account_qr);qm_account_qr=image;qm_account_qr_width=w;qm_account_qr_height=h;
    state=AUTH_SCAN;snprintf(message,sizeof message,"请用%s扫码，再在手机上确认",kind==1?"微信":"QQ");return 1;
}
static int get_qq_qr(uint32_t id,char identifier[256])
{
    char url[256];snprintf(url,sizeof url,"https://ssl.ptlogin2.qq.com/ptqrshow?appid=716027609&e=2&l=M&s=3&d=72&v=4&t=0.%lu&daid=383&pt_3rd_aid=100497308",(unsigned long)auth_random());
    auth_reply *r=http(id,url,NULL,NULL,NULL,QR_LIMIT);
    int ok=r&&cookie_get(r->cookies,"qrsig",identifier,256)&&publish_qr(id,r);
    reply_free(r);return ok;
}
static int get_wx_qr(uint32_t id,char identifier[256])
{
    char redirect[512],url[1024];
    if(!encode(redirect,sizeof redirect,"https://y.qq.com/portal/wx_redirect.html?login_type=2&surl=https://y.qq.com/"))return 0;
    snprintf(url,sizeof url,"https://open.weixin.qq.com/connect/qrconnect?appid=wx48db31d50e334801&redirect_uri=%s&response_type=code&scope=snsapi_login&state=STATE&href=https%%3A%%2F%%2Fy.qq.com%%2Fmediastyle%%2Fmusic_v17%%2Fsrc%%2Fcss%%2Fpopup_wechat.css%%23wechat_redirect",redirect);
    auth_reply *r=http(id,url,NULL,NULL,NULL,65536);if(!r)return 0;
    const char *start=strstr((const char *)r->body,"uuid=");
    if(start)start+=5;else {start=strstr((const char *)r->body,"/connect/qrcode/");if(start)start+=16;}
    unsigned n=0;if(start)while(start[n]&&start[n]!='\''&&start[n]!='"'&&start[n]!='&'&&n<255){identifier[n]=start[n];n++;}
    identifier[n]=0;reply_free(r);
    if(!n||n>=255)return 0;
    for(unsigned i=0;i<n;i++)if(!((identifier[i]>='a'&&identifier[i]<='z')||(identifier[i]>='A'&&identifier[i]<='Z')||(identifier[i]>='0'&&identifier[i]<='9')||identifier[i]=='_'||identifier[i]=='-'))return 0;
    snprintf(url,sizeof url,"https://open.weixin.qq.com/connect/qrcode/%s",identifier);
    r=http(id,url,NULL,NULL,NULL,QR_LIMIT);int ok=publish_qr(id,r);reply_free(r);return ok;
}
static cJSON *poll_login(uint32_t id,unsigned type,const char *identifier,int *event)
{
    char url[1024],cookie[300]="";
    if(type==2){
        snprintf(url,sizeof url,"https://ssl.ptlogin2.qq.com/ptqrlogin?u1=https%%3A%%2F%%2Fgraph.qq.com%%2Foauth2.0%%2Flogin_jump&ptqrtoken=%lu&ptredirect=0&h=1&t=1&g=1&from_ui=1&ptlang=2052&action=0-0-%llu&js_ver=20102616&js_type=1&pt_uistyle=40&aid=716027609&daid=383&pt_3rd_aid=100497308&has_onekey=1",
            (unsigned long)hash33(identifier,0),(unsigned long long)time(NULL)*1000);
        snprintf(cookie,sizeof cookie,"qrsig=%s",identifier);
    }else snprintf(url,sizeof url,"https://lp.open.weixin.qq.com/connect/l/qrconnect?uuid=%s&_=%llu",identifier,(unsigned long long)time(NULL)*1000);
    auth_reply *r=http(id,url,NULL,NULL,cookie,32768);h1net_secure_clear(cookie,sizeof cookie);
    if(!r)return NULL;cJSON *credential_data=NULL;
    if(type==2){
        char code[16],redirect[2048];
        if(quoted((const char *)r->body,0,code,sizeof code)){
            char *end;unsigned value=(unsigned)strtoul(code,&end,10);
            if(!*code||*end){reply_free(r);return NULL;}
            if(value==0&&quoted((const char *)r->body,2,redirect,sizeof redirect)){credential_data=authorize_qq(id,redirect);*event=credential_data?AUTH_DONE:AUTH_ERROR;}
            else if(value==67)*event=AUTH_CONFIRM;
            else if(value==65||value==68)*event=AUTH_EXPIRED;
        }
    }else {
        const char *p=strstr((const char *)r->body,"wx_errcode=");
        unsigned value=p?(unsigned)strtoul(p+11,NULL,10):0;
        if(value==405){
            p=strstr((const char *)r->body,"wx_code='");
            if(p){char code[512];p+=9;const char *end=strchr(p,'\'');
                if(end&&(unsigned)(end-p)<sizeof code){memcpy(code,p,(size_t)(end-p));code[end-p]=0;
                    cJSON *param=cJSON_CreateObject();cJSON_AddStringToObject(param,"code",code);cJSON_AddStringToObject(param,"strAppid","wx48db31d50e334801");
                    credential_data=cgi(id,"music.login.LoginServer","Login",param,1,NULL);h1net_secure_clear(code,sizeof code);
                }
            }*event=credential_data?AUTH_DONE:AUTH_ERROR;
        }else if(value==404)*event=AUTH_CONFIRM;else if(value==402||value==403)*event=AUTH_EXPIRED;
    }
    reply_free(r);return credential_data;
}
static void copy_text(char *out,unsigned cap,const char *text)
{
    unsigned n=(unsigned)strlen(text);if(n>=cap){n=cap-1;while(n&&((unsigned char)text[n]&0xc0)==0x80)n--;}
    memcpy(out,text,n);out[n]=0;
}
/* -1 is a transport failure, 0 valid, 1 explicitly rejected by the service. */
static int validate(uint32_t id,cJSON *data,char nick[96])
{
    char cookie[1024],uin[32],url[512];if(!credential_cookie(data,cookie,uin))return 1;
    snprintf(url,sizeof url,"https://c6.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg?g_tk=%lu&format=json&inCharset=utf-8&outCharset=utf-8&notice=0&cid=205360838&needNewCode=0&loginUin=%s&hostUin=0&userid=%s&reqfrom=1",(unsigned long)hash33(string(data,"musickey"),5381),uin,uin);
    auth_reply *r=http(id,url,NULL,NULL,cookie,65536);h1net_secure_clear(cookie,sizeof cookie);
    int result=-1;
    if(r&&r->status==200){cJSON *root=cJSON_Parse((const char *)r->body),*code=cJSON_GetObjectItemCaseSensitive(root,"code");
        if(cJSON_IsNumber(code)){result=code->valueint?1:0;if(!result)copy_text(nick,96,find_nick(root,0));}
        cJSON_Delete(root);
    }
    reply_free(r);return result;
}
static int restore(uint32_t id)
{
    char *copy=credential_copy();cJSON *data=copy?cJSON_Parse(copy):NULL;
    if(copy)erase_free(copy,(unsigned)strlen(copy));if(!data)return 1;
    char nick[96]="";int result=validate(id,data,nick);
    if(!result){take();if(id==session&&!cancelled){logged=true;state=AUTH_DONE;error_code=0;
            if(*nick)copy_text(nickname,sizeof nickname,nick);
            else snprintf(nickname,sizeof nickname,"%s账号",login_type(data)==1?"微信":"QQ");
            snprintf(message,sizeof message,"已恢复登录状态");}give();
    }else if(result>0){
        cJSON *param=cJSON_CreateObject();
        static const char *fields[]={"openid","access_token","refresh_token","musickey","unionid","refresh_key","musicid","str_musicid"};
        for(unsigned i=0;i<sizeof fields/sizeof *fields;i++){cJSON *v=cJSON_GetObjectItemCaseSensitive(data,fields[i]);if(v)cJSON_AddItemToObject(param,fields[i],cJSON_Duplicate(v,true));}
        cJSON *expiry=cJSON_GetObjectItemCaseSensitive(data,"expired_in");if(!expiry)expiry=cJSON_GetObjectItemCaseSensitive(data,"expired_at");
        if(expiry)cJSON_AddItemToObject(param,"expired_in",cJSON_Duplicate(expiry,true));
        cJSON_AddNumberToObject(param,"loginMode",2);
        take();error_code=0;give();
        cJSON *fresh=cgi(id,"music.login.LoginServer","Login",param,login_type(data),data);
        if(fresh){cJSON_AddNumberToObject(fresh,"loginType",login_type(data));result=save_credential(id,fresh)?0:-1;cJSON_Delete(fresh);}
        else {take();result=error_code?1:-1;give();}
    }
    cJSON_Delete(data);return result;
}

/* Two verified generations keep a failed write from destroying the last login.
 * A zero-length newest generation is a durable logout tombstone. */
static uint32_t generation;
static unsigned slot;
static void path(unsigned index,char out[40]){snprintf(out,40,"A:\\QQMusic.auth%u",index);}
static char *read_slot(unsigned index,uint32_t *gen,int *valid)
{
    char name[40];path(index,name);h1_file *file=h1_fopen(name,"rb");*valid=0;if(!file)return NULL;
    uint8_t header[24];char *text=NULL;
    if(h1_fread(header,1,24,file)==24&&h1net_u32(header)==0x31414d51u&&h1net_u32(header+4)==1&&
        h1net_u32(header+20)==h1net_crc32(header,20)){
        unsigned n=h1net_u32(header+12);
        if(n<CREDENTIAL_LIMIT){text=calloc(1,n+1);if(text&&(!n||h1_fread(text,1,n,file)==n)&&h1net_crc32(text,n)==h1net_u32(header+16)){
                *valid=1;*gen=h1net_u32(header+8);
            }else {erase_free(text,n);text=NULL;}}
    }
    h1_fclose(file);return text;
}
static int store(const char *text)
{
    unsigned n=text?(unsigned)strlen(text):0,index=slot^1;uint8_t header[24];char name[40];path(index,name);
    h1net_put32(header,0x31414d51u);h1net_put32(header+4,1);h1net_put32(header+8,generation+1);
    h1net_put32(header+12,n);h1net_put32(header+16,h1net_crc32(text,n));h1net_put32(header+20,h1net_crc32(header,20));
    h1_file *file=h1_fopen(name,"wb");if(!file)return 0;
    int ok=h1_fwrite(header,1,24,file)==24&&(!n||h1_fwrite(text,1,n,file)==n),closed=h1_fclose(file)==0;
    uint32_t gen=0;int valid=0;char *check=read_slot(index,&gen,&valid);
    ok=ok&&closed&&valid&&gen==generation+1&&check&&strlen(check)==n&&(!n||!memcmp(check,text,n));
    if(check)erase_free(check,(unsigned)strlen(check));
    if(ok){generation++;slot=index;}return ok;
}
void qm_account_init(void)
{
    if(loaded)return;loaded=1;uint32_t gens[2]={0};int valid[2]={0};char *values[2];
    values[0]=read_slot(0,&gens[0],&valid[0]);values[1]=read_slot(1,&gens[1],&valid[1]);
    if(valid[0]||valid[1]){slot=valid[1]&&(!valid[0]||(int32_t)(gens[1]-gens[0])>0)?1:0;generation=gens[slot];
        if(values[slot]&&*values[slot]){cJSON *data=cJSON_Parse(values[slot]);char cookie[1024],uin[32];
            if(data&&credential_cookie(data,cookie,uin)){credential=values[slot];values[slot]=NULL;state=AUTH_RESTORE;kind=login_type(data);snprintf(message,sizeof message,"正在恢复登录状态");}
            h1net_secure_clear(cookie,sizeof cookie);cJSON_Delete(data);}}
    for(unsigned i=0;i<2;i++)if(values[i])erase_free(values[i],(unsigned)strlen(values[i]));
}
void qm_account_begin(unsigned type)
{
    session++;kind=type;state=AUTH_FETCHING;error_code=0;pending=1;cancelled=0;next_poll=0;
    free(qm_account_qr);qm_account_qr=NULL;qm_account_qr_width=qm_account_qr_height=0;
    snprintf(message,sizeof message,"正在获取%s二维码",type==1?"微信":"QQ");
}
void qm_account_cancel(void)
{
    session++;pending=0;cancelled=0;h1net_secure_clear(login_identifier,sizeof login_identifier);
    if(state==AUTH_FETCHING||state==AUTH_SCAN||state==AUTH_CONFIRM){state=logged?AUTH_DONE:credential?AUTH_RESTORE:AUTH_IDLE;snprintf(message,sizeof message,"已取消扫码");}
    free(qm_account_qr);qm_account_qr=NULL;qm_account_qr_width=qm_account_qr_height=0;
}
void qm_account_close(void)
{qm_account_cancel();if(credential){erase_free(credential,(unsigned)strlen(credential));credential=NULL;}}
int qm_account_logout(void)
{
    if(!store(NULL)){snprintf(message,sizeof message,"退出保存失败，请检查存储空间");return 0;}
    qm_account_cancel();if(credential){erase_free(credential,(unsigned)strlen(credential));credential=NULL;}
    logged=0;state=AUTH_IDLE;nickname[0]=0;error_code=0;qm_account_revision++;snprintf(message,sizeof message,"已退出登录");
    /* Tombstone is already verified; remove the older account copy. */
    char name[40];path(slot^1,name);h1_remove(name);return 1;
}
void qm_account_step(int visible)
{
    if(qm_connection_status!=QM_NETWORK_READY||(int32_t)(qm_time()-next_poll)<0)return;
    uint32_t id=session;next_poll=qm_time()+2000;
    if(pending&&visible){
        pending=0;
        if(!(qm_net_features()&H1NET_CAP_HTTP_HEADERS)){change(id,AUTH_ERROR,"请更新ESP通用固件至0.4.4");return;}
        int ok=kind==1?get_wx_qr(id,login_identifier):get_qq_qr(id,login_identifier);
        if(!ok)change(id,AUTH_ERROR,"获取二维码失败，按R重试");
        else expires=qm_time()+180000;next_poll=qm_time()+2000;
    }else if(visible&&(state==AUTH_SCAN||state==AUTH_CONFIRM)){
        if((int32_t)(qm_time()-expires)>=0){change(id,AUTH_EXPIRED,"二维码已过期，按R刷新");return;}
        int event=AUTH_SCAN;cJSON *data=poll_login(id,kind,login_identifier,&event);
        if(data){cJSON_DeleteItemFromObjectCaseSensitive(data,"loginType");cJSON_AddNumberToObject(data,"loginType",kind);
            if(!save_credential(id,data)&&state!=AUTH_ERROR)change(id,AUTH_ERROR,"授权失败，请重试");cJSON_Delete(data);
            h1net_secure_clear(login_identifier,sizeof login_identifier);
        }else if(event==AUTH_ERROR)change(id,AUTH_ERROR,"授权失败，按R重新扫码");
        else if(event==AUTH_EXPIRED)change(id,AUTH_EXPIRED,"二维码已过期，按R刷新");
        else change(id,(unsigned)event,event==AUTH_CONFIRM?"已扫码，请在手机上确认":"等待扫码，随后在手机上确认");
        next_poll=qm_time()+2000;
    }else if(credential&&(state==AUTH_RESTORE||state==AUTH_DONE)){
        int result=restore(id);
        if(result<0){change(id,AUTH_RESTORE,"暂时无法验证，联网后自动重试");next_poll=qm_time()+30000;}
        else if(result>0){logged=0;qm_account_revision++;change(id,AUTH_EXPIRED,"登录已过期，请重新扫码");}
        else next_poll=qm_time()+1800000;
    }
}
/* Never attach account cookies to arbitrary URLs or follow redirects with them. */
static int trusted(const char *url)
{
    static const char *hosts[]={"u.y.qq.com","c.y.qq.com","c6.y.qq.com"};
    if(strncmp(url,"https://",8))return 0;
    for(unsigned i=0;i<sizeof hosts/sizeof *hosts;i++){unsigned n=(unsigned)strlen(hosts[i]);if(!strncmp(url+8,hosts[i],n)&&url[8+n]=='/')return 1;}
    return 0;
}
static void set_string(cJSON *object,const char *key,const char *value)
{cJSON_DeleteItemFromObjectCaseSensitive(object,key);cJSON_AddStringToObject(object,key,value);}
static void set_number(cJSON *object,const char *key,double value)
{cJSON_DeleteItemFromObjectCaseSensitive(object,key);cJSON_AddNumberToObject(object,key,value);}
int qm_account_authorize(const char *url,const char *headers_text,const void *body,unsigned n,char **out_headers,char **out_body,unsigned *out_n)
{
    *out_headers=*out_body=NULL;*out_n=n;if(!trusted(url))return 0;
    take();bool use=logged;give();if(!use)return 0;
    char *copy=credential_copy();cJSON *data=copy?cJSON_Parse(copy):NULL;if(copy)erase_free(copy,(unsigned)strlen(copy));
    char cookie[1024],uin[32];if(!data||!credential_cookie(data,cookie,uin)){cJSON_Delete(data);return -1;}
    unsigned used=0;char filtered[H1NET_MAX_HEADERS+1];
    for(const char *p=headers_text;p&&*p;){const char *end=strstr(p,"\r\n");if(!end)end=p+strlen(p);unsigned size=(unsigned)(end-p);
        if(strncasecmp(p,"Cookie:",7)){if(used+size+2>H1NET_MAX_HEADERS)goto fail;memcpy(filtered+used,p,size);used+=size;filtered[used++]='\r';filtered[used++]='\n';}
        p=*end?end+2:end;
    }
    if(used+8+strlen(cookie)>H1NET_MAX_HEADERS)goto fail;
    memcpy(filtered+used,"Cookie: ",8);used+=8;strcpy(filtered+used,cookie);
    *out_headers=strdup(filtered);if(!*out_headers)goto fail;
    if(body&&n&&strstr(url+8,"/cgi-bin/musicu.fcg")){
        char *input=malloc(n+1);if(!input)goto fail;memcpy(input,body,n);input[n]=0;cJSON *root=cJSON_Parse(input);erase_free(input,n);
        if(!cJSON_IsObject(root)){cJSON_Delete(root);goto fail;}
        cJSON *comm=cJSON_GetObjectItemCaseSensitive(root,"comm");if(!cJSON_IsObject(comm)){cJSON_DeleteItemFromObjectCaseSensitive(root,"comm");comm=cJSON_AddObjectToObject(root,"comm");}
        set_string(comm,"uin",uin);set_string(comm,"authst",string(data,"musickey"));set_number(comm,"tmeLoginType",login_type(data));
        set_number(comm,"g_tk",hash33(string(data,"musickey"),5381));
        cJSON *request;cJSON_ArrayForEach(request,root){const char *module=string(request,"module");cJSON *param=cJSON_GetObjectItemCaseSensitive(request,"param");
            if(cJSON_IsObject(param)&&!strncmp(module,"vkey.",5)){set_string(param,"uin",uin);set_number(param,"loginflag",1);}}
        *out_body=cJSON_PrintUnformatted(root);cJSON_Delete(root);
        if(!*out_body||strlen(*out_body)>H1NET_MAX_REQUEST_BODY)goto fail;*out_n=(unsigned)strlen(*out_body);
    }
    h1net_secure_clear(filtered,sizeof filtered);h1net_secure_clear(cookie,sizeof cookie);cJSON_Delete(data);return 1;
fail:
    if(*out_headers){erase_free(*out_headers,(unsigned)strlen(*out_headers));*out_headers=NULL;}
    if(*out_body){erase_free(*out_body,(unsigned)strlen(*out_body));*out_body=NULL;}
    h1net_secure_clear(filtered,sizeof filtered);h1net_secure_clear(cookie,sizeof cookie);cJSON_Delete(data);return -1;
}
