/* Private bounded JSON tokenizer; preserves LRC line breaks. */
enum {OBJ=1,ARR,STR,NUM,LIT};
typedef struct {unsigned start,end,next;unsigned char kind;} token;
typedef struct {const char *s;size_t n,at;token *t;unsigned used,cap;} parser;
static void ws(parser *p){while(p->at<p->n && strchr(" \r\n\t",p->s[p->at]))++p->at;}
static int hex(int c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
static int value(parser *p,unsigned depth)
{
    ws(p);if(depth>32 || p->used==p->cap || p->at==p->n)return -1;
    unsigned i=++p->used;token *t=p->t+i;t->start=p->at;
    if(!(i&255u)&&parse_progress)parse_progress();
    char c=p->s[p->at++];
    if(c=='{' || c=='['){
        t->kind=c=='{'?OBJ:ARR;char end=c=='{'?'}':']';ws(p);
        if(p->at<p->n && p->s[p->at]==end)++p->at;
        else for(;;){
            if(t->kind==OBJ){ws(p);if(p->at==p->n || p->s[p->at]!='"' || value(p,depth+1)<0)return -1;ws(p);if(p->at==p->n || p->s[p->at++]!=':')return -1;}
            if(value(p,depth+1)<0)return -1;ws(p);if(p->at==p->n)return -1;
            char sep=p->s[p->at++];if(sep==end)break;if(sep!=',')return -1;
        }
    }else if(c=='"'){
        t->kind=STR;t->start=p->at;int closed=0;
        while(p->at<p->n){unsigned ch=(unsigned char)p->s[p->at++];if(ch=='"'){closed=1;break;}if(ch<32)return -1;
            if(ch=='\\'){if(p->at==p->n)return -1;ch=p->s[p->at++];if(ch=='u'){for(int k=0;k<4;k++)if(p->at==p->n || hex(p->s[p->at++])<0)return -1;}else if(!strchr("\"\\/bfnrt",ch))return -1;}}
        if(!closed)return -1;
    }else{
        while(p->at<p->n && !strchr(",]} \r\n\t",p->s[p->at]))++p->at;
        size_t n=p->at-t->start;const char *s=p->s+t->start;
        if((n==4 && (!memcmp(s,"true",4)||!memcmp(s,"null",4))) || (n==5&&!memcmp(s,"false",5)))t->kind=LIT;
        else {
            size_t k=0;if(k<n && s[k]=='-')++k;if(k==n)return -1;
            if(s[k]=='0')++k;else{if(s[k]<'1'||s[k]>'9')return -1;while(k<n&&s[k]>='0'&&s[k]<='9')++k;}
            if(k<n&&s[k]=='.'){++k;size_t a=k;while(k<n&&s[k]>='0'&&s[k]<='9')++k;if(k==a)return -1;}
            if(k<n&&(s[k]=='e'||s[k]=='E')){++k;if(k<n&&(s[k]=='+'||s[k]=='-'))++k;size_t a=k;while(k<n&&s[k]>='0'&&s[k]<='9')++k;if(k==a)return -1;}
            if(k!=n)return -1;t->kind=NUM;
        }
    }
    t->end=p->at-(t->kind==STR);t->next=p->used+1;return (int)i;
}
static int open_json(parser *p,const char *s,size_t n)
{
    memset(p,0,sizeof *p);if(!n || n>384u*1024u || memchr(s,0,n))return -1;
    p->s=s;p->n=n;p->cap=16384;p->t=calloc(p->cap+1,sizeof(token));if(!p->t)return -1;
    int r=value(p,0);ws(p);return r==1 && p->at==n && p->t[1].kind==OBJ?0:-1;
}
static int eq(parser *p,unsigned i,const char *s){return i && p->t[i].kind==STR && p->t[i].end-p->t[i].start==strlen(s)&&!memcmp(p->s+p->t[i].start,s,strlen(s));}
static unsigned get(parser *p,unsigned i,const char *s)
{
    if(!i || p->t[i].kind!=OBJ)return 0;
    for(unsigned k=i+1;k<p->t[i].next;){unsigned v=k+1;if(eq(p,k,s))return v;k=p->t[v].next;}return 0;
}
static void utf8(char *out,size_t cap,size_t *at,unsigned cp)
{
    char b[4];unsigned n;if(cp<128){b[0]=cp;n=1;}else if(cp<2048){b[0]=192|(cp>>6);b[1]=128|(cp&63);n=2;}
    else if(cp<65536){b[0]=224|(cp>>12);b[1]=128|((cp>>6)&63);b[2]=128|(cp&63);n=3;}
    else{b[0]=240|(cp>>18);b[1]=128|((cp>>12)&63);b[2]=128|((cp>>6)&63);b[3]=128|(cp&63);n=4;}
    if(*at+n<cap){memcpy(out+*at,b,n);*at+=n;}
}
static int string(parser *p,unsigned i,char *out,size_t cap)
{
    if(!cap)return -1;out[0]=0;if(!i || p->t[i].kind!=STR)return -1;
    unsigned a=p->t[i].start,end=p->t[i].end;size_t n=0;int truncated=0;
    while(a<end){unsigned c=(unsigned char)p->s[a++];
        if(c=='\\'){c=(unsigned char)p->s[a++];if(c=='u'){
            unsigned cp=0;for(int k=0;k<4;k++)cp=(cp<<4)|hex(p->s[a++]);
            if(cp>=0xd800&&cp<=0xdbff){if(a+6>end || p->s[a]!='\\'||p->s[a+1]!='u')goto bad_string;a+=2;unsigned low=0;for(int k=0;k<4;k++)low=(low<<4)|hex(p->s[a++]);if(low<0xdc00||low>0xdfff)goto bad_string;cp=0x10000+((cp-0xd800)<<10)+low-0xdc00;}
            else if(cp>=0xdc00&&cp<=0xdfff)goto bad_string;
            if(!cp)goto bad_string;size_t before=n;utf8(out,cap,&n,cp);if(n==before)truncated=1;continue;
        }else if(c=='n')c='\n';else if(c=='r')c='\r';else if(c=='t')c='\t';else if(c=='b'||c=='f')c=' ';}
        if(n+1<cap)out[n++]=(char)c;else truncated=1;
    }out[n]=0;
    /* Truncate only at a UTF-8 boundary. */
    if(n && ((unsigned char)out[n-1]&128)){size_t k=n-1;while(k && ((unsigned char)out[k]&192)==128)--k;unsigned lead=(unsigned char)out[k],want=lead>=240?4:lead>=224?3:2;if(n-k<want)out[k]=0;}
    return truncated?-1:0;
bad_string:out[0]=0;return -1;
}
static int digits(parser *p,unsigned i,char *out,size_t cap)
{
    if(!i || (p->t[i].kind!=NUM && p->t[i].kind!=STR))return -1;
    unsigned a=p->t[i].start,n=p->t[i].end-a;if(!n || n>=cap || n>20)return -1;
    for(unsigned k=0;k<n;k++)if(p->s[a+k]<'0'||p->s[a+k]>'9')return -1;
    memcpy(out,p->s+a,n);out[n]=0;return 0;
}
static unsigned number(parser *p,unsigned i){char b[24];if(digits(p,i,b,sizeof b))return 0;unsigned long long v=strtoull(b,NULL,10);return v<=UINT_MAX?(unsigned)v:0;}
