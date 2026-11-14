#include "core.h"
#include "h1net_wire.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
static void (*parse_progress)(void);
void qm_set_parse_progress(void (*fn)(void)){parse_progress=fn;}
#include "json.h"
static int identifier(const char *s)
{unsigned n=0;for(;s[n];n++)if(n>=14||!((s[n]>='a'&&s[n]<='z')||(s[n]>='A'&&s[n]<='Z')||(s[n]>='0'&&s[n]<='9')))return 0;return n==14;}
static int success(parser *p,unsigned object)
{unsigned code=get(p,object,"code");char n[24];return code&&!digits(p,code,n,sizeof n)&&!strcmp(n,"0");}
static void clean(char *s)
{char *out=s;int tag=0;for(char *p=s;*p;p++){if(*p=='<'){tag=1;continue;}if(*p=='>'){tag=0;continue;}if(!tag)*out++=(unsigned char)*p<32?' ':*p;}*out=0;}
static void track(parser *p,unsigned object,qm_track *out)
{
    memset(out,0,sizeof *out);(void)string(p,get(p,object,"songmid"),out->mid,sizeof out->mid);
    (void)string(p,get(p,object,"strMediaMid"),out->media,sizeof out->media);
    (void)string(p,get(p,object,"albummid"),out->album,sizeof out->album);
    (void)string(p,get(p,object,"songname"),out->title,sizeof out->title);clean(out->title);
    if(!identifier(out->media))memcpy(out->media,out->mid,sizeof out->media);
    unsigned singers=get(p,object,"singer"),used=0;
    if(singers&&p->t[singers].kind==ARR)for(unsigned i=singers+1;i<p->t[singers].next;i=p->t[i].next){
        char name[80];if(string(p,get(p,i,"name"),name,sizeof name))continue;clean(name);unsigned n=(unsigned)strlen(name);
        if(n+used+(used?3:0)>=sizeof out->artist)break;
        if(used){memcpy(out->artist+used," / ",3);used+=3;}memcpy(out->artist+used,name,n+1);used+=n;
    }
    out->seconds=number(p,get(p,object,"interval"));unsigned permission=get(p,get(p,object,"pay"),"payplay");
    out->paid=permission?(number(p,permission)!=0):2; /* TMC: missing rights are unknown; download cost is independent. */
}
int qm_parse_list(const char *data,size_t length,qm_list *out,char error[128])
{
    parser p;int result=-1;error[0]=0;memset(out,0,sizeof *out);
    if(open_json(&p,data,length))goto done;
    if(!success(&p,1)){snprintf(error,128,"QQ音乐接口暂不可用");goto done;}
    unsigned entries=get(&p,1,"songlist"),song=get(&p,get(&p,1,"data"),"song");
    if(song){entries=get(&p,song,"list");out->page=number(&p,get(&p,song,"curpage"));out->total=number(&p,get(&p,song,"totalnum"));}
    else {out->page=number(&p,get(&p,1,"song_begin"))/QM_TRACKS+1;out->total=number(&p,get(&p,1,"total_song_num"));}
    if(!entries||p.t[entries].kind!=ARR){snprintf(error,128,"歌曲列表格式已变化");goto done;}
    for(unsigned i=entries+1;i<p.t[entries].next&&out->count<QM_TRACKS;i=p.t[i].next){
        unsigned object=get(&p,i,"data");qm_track candidate;track(&p,object?object:i,&candidate);
        if(!identifier(candidate.mid)||!identifier(candidate.media)||!candidate.title[0])continue;
        int duplicate=0;for(unsigned n=0;n<out->count;n++)if(!strcmp(out->tracks[n].mid,candidate.mid))duplicate=1;
        if(!duplicate)out->tracks[out->count++]=candidate;
    }
    if(!out->page)out->page=1;result=0;
done:free(p.t);if(result&&!error[0])snprintf(error,128,"歌曲数据不完整或格式错误");return result;
}
int qm_parse_url(const char *data,size_t length,const char *mid,char url[401],char error[128])
{
    parser p;int result=-1;url[0]=error[0]=0;if(!identifier(mid))return -1;
    if(open_json(&p,data,length))goto done;
    unsigned req=get(&p,1,"req"),body=get(&p,req,"data");
    if(!success(&p,1)||!success(&p,req)||number(&p,get(&p,body,"retcode"))){snprintf(error,128,"QQ音乐暂未提供播放地址");goto done;}
    unsigned list=get(&p,body,"midurlinfo"),servers=get(&p,body,"sip");char path[360]={0},base[160]={0};
    if(!list||p.t[list].kind!=ARR)goto done;
    for(unsigned i=list+1;i<p.t[list].next;i=p.t[i].next){char id[15];if(string(&p,get(&p,i,"songmid"),id,sizeof id)||strcmp(mid,id))continue;
        if(number(&p,get(&p,i,"result"))||number(&p,get(&p,i,"pneedbuy"))){snprintf(error,128,"此歌曲需要账号授权或购买");result=1;goto done;}
        if(string(&p,get(&p,i,"purl"),path,sizeof path))goto done;
        if(!path[0]){snprintf(error,128,"此歌曲暂无可用播放权限");result=1;goto done;}break;
    }
    if(!path[0]||strncmp(path,"C400",4)||strstr(path,"..")||strchr(path,':')||path[0]=='/')goto done;
    if(!servers||p.t[servers].kind!=ARR||servers+1>=p.t[servers].next||string(&p,servers+1,base,sizeof base))goto done;
    if(!strncmp(base,"http://",7)){char secure[160];snprintf(secure,sizeof secure,"https://%s",base+7);memcpy(base,secure,sizeof base);}
    if(strncmp(base,"https://",8)||base[strlen(base)-1]!='/')goto done;
    int n=snprintf(url,401,"%s%s",base,path);if(n<=0||n>400||!h1net_valid_url((const uint8_t *)url,(unsigned)n)){url[0]=0;goto done;}
    result=0;
done:free(p.t);if(result&&!error[0])snprintf(error,128,"播放地址格式不受支持");return result;
}
int qm_search_url(const char *query,unsigned page,int search,char url[401])
{
    if(!page||page>999)return -1;
    if(!search){snprintf(url,401,"https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg?format=json&topid=26&song_begin=%u&song_num=12",(page-1)*QM_TRACKS);return 0;}
    char quoted[145];unsigned n=0;static const char hexes[]="0123456789ABCDEF";size_t length=strlen(query);if(!length||length>48)return -1;
    for(unsigned i=0;i<length;i++){unsigned c=(unsigned char)query[i];if(c<32||c==127)return -1;
        quoted[n++]='%';quoted[n++]=hexes[c>>4];quoted[n++]=hexes[c&15];}quoted[n]=0;
    int r=snprintf(url,401,"https://c.y.qq.com/soso/fcgi-bin/client_search_cp?format=json&inCharset=utf8&outCharset=utf8&platform=yqq&p=%u&n=12&w=%s",page,quoted);return r>0&&r<=400?0:-1;
}
int qm_vkey_body(const qm_track *s,uint32_t guid,char body[640])
{
    if(!s||!identifier(s->mid)||!identifier(s->media))return -1;
    return snprintf(body,640,"{\"comm\":{\"ct\":24,\"cv\":0,\"format\":\"json\"},\"req\":{\"module\":\"vkey.GetVkeyServer\",\"method\":\"CgiGetVkey\",\"param\":{\"guid\":\"%lu\",\"songmid\":[\"%s\"],\"songtype\":[0],\"uin\":\"0\",\"loginflag\":1,\"platform\":\"20\",\"filename\":[\"C400%s.m4a\"]}}}",(unsigned long)guid,s->mid,s->media);
}
int qm_cover_url(const qm_track *s,char url[401])
{if(!identifier(s->album))return -1;snprintf(url,401,"https://y.gtimg.cn/music/photo_new/T002R180x180M000%s.jpg",s->album);return 0;}
static unsigned base64(char *s)
{
    unsigned bits=0,value=0,n=0;for(unsigned i=0;s[i]&&s[i]!='=';i++){
        unsigned c=(unsigned char)s[i],v=c>='A'&&c<='Z'?c-'A':c>='a'&&c<='z'?c-'a'+26:c>='0'&&c<='9'?c-'0'+52:c=='+'?62:c=='/'?63:99;
        if(v>63)return 0;value=(value<<6)|v;bits+=6;if(bits>=8){bits-=8;s[n++]=(char)(value>>bits);}}
    s[n]=0;return n;
}
int qm_parse_lyrics(const char *data,size_t length,qm_lyrics *out)
{
    parser p;memset(out,0,sizeof *out);char *raw=NULL;int result=-1;
    if(open_json(&p,data,length)||!success(&p,1))goto done;raw=malloc(32769);if(!raw)goto done;
    if(string(&p,get(&p,1,"lyric"),raw,32769))goto done;
    if(raw[0]&&raw[0]!='['&&!strchr(raw,'\n')){if(!base64(raw))goto done;}
    long offset=0;char *offset_tag=strstr(raw,"[offset:");if(offset_tag){offset=strtol(offset_tag+8,NULL,10);if(offset>600000||offset<-600000)offset=0;}
    for(char *at=raw;*at&&out->count<QM_LINES;){char *end=strchr(at,'\n');if(end)*end=0;uint32_t times[8];unsigned count=0;char *s=at;
        while(*s=='['){char *close=strchr(s,']');if(!close)break;unsigned m=0,sec=0,fraction=0;char *a=s+1;
            if(*a<'0'||*a>'9')break;while(*a>='0'&&*a<='9'){m=m*10+(unsigned)(*a++-'0');if(m>999)break;}
            if(*a++!=':')break;unsigned digits_count=0;while(*a>='0'&&*a<='9'){sec=sec*10+(unsigned)(*a++-'0');digits_count++;}
            if(sec>=60||!digits_count)break;
            if(*a=='.'){a++;unsigned scale=100;while(*a>='0'&&*a<='9'){if(scale)fraction+=(unsigned)(*a-'0')*scale;scale/=10;a++;}}
            if(a!=close||m>999)break;if(count<8)times[count++]=m*60000+sec*1000+fraction;s=close+1;
        }
        if(count&&*s)for(unsigned i=0;i<count&&out->count<QM_LINES;i++){
            qm_line *line=out->lines+out->count++;int64_t ms=(int64_t)times[i]+offset;line->ms=ms<0?0:(uint32_t)ms;snprintf(line->text,sizeof line->text,"%s",s);clean(line->text);
            size_t n=strlen(line->text);if(n&&((unsigned char)line->text[n-1]&128)){size_t k=n-1;while(k&&((unsigned char)line->text[k]&192)==128)k--;unsigned lead=(unsigned char)line->text[k],want=lead>=240?4:lead>=224?3:2;if(n-k<want)line->text[k]=0;}
        }
        if(!end)break;at=end+1;
    }
    for(unsigned i=1;i<out->count;i++){qm_line line=out->lines[i];unsigned at=i;while(at&&out->lines[at-1].ms>line.ms){out->lines[at]=out->lines[at-1];at--;}out->lines[at]=line;}
    result=0;
done:free(raw);free(p.t);return result;
}
unsigned qm_lyric_at(const qm_lyrics *lyrics,uint32_t ms)
{if(!lyrics->count||lyrics->lines[0].ms>ms)return UINT_MAX;unsigned at=0;while(at+1<lyrics->count&&lyrics->lines[at+1].ms<=ms)at++;return at;}
