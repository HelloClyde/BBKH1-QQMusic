#include "queue.h"
#include <string.h>
static void reset_history(qm_queue_policy *q)
{
    q->remaining=(1u<<q->count)-1u;
    if(q->count){q->remaining&=~(1u<<q->current);q->history[0]=q->current;q->length=1;}
    else q->length=0;q->position=0;
}
void qm_queue_begin(qm_queue_policy *q,unsigned count,unsigned current,unsigned mode,uint32_t seed)
{
    memset(q,0,sizeof *q);q->count=count>QM_TRACKS?QM_TRACKS:count;
    q->current=current<q->count?current:0;q->mode=mode<QM_PLAY_MODES?mode:QM_PLAY_ORDER;
    q->random=seed?seed:0x514d5731u;reset_history(q);
}
void qm_queue_mode(qm_queue_policy *q,unsigned mode)
{q->mode=mode<QM_PLAY_MODES?mode:QM_PLAY_ORDER;reset_history(q);}
const char *qm_queue_label(unsigned mode)
{static const char *labels[]={"顺序播放","列表循环","单曲循环","随机播放"};return labels[mode<QM_PLAY_MODES?mode:0];}
unsigned qm_queue_move(qm_queue_policy *q,int action)
{
    if(!q->count||q->current>=q->count)return QM_TRACKS;
    if(q->mode==QM_PLAY_SINGLE_LOOP&&action==QM_QUEUE_ENDED)return q->current;
    if(q->mode==QM_PLAY_SHUFFLE){
        if(action==QM_QUEUE_PREVIOUS){if(!q->position)return QM_TRACKS;return q->current=q->history[--q->position];}
        if(q->position+1<q->length)return q->current=q->history[++q->position];
        if(!q->remaining)q->remaining=((1u<<q->count)-1u)&~(q->count>1?1u<<q->current:0u);
        q->random^=q->random<<13;q->random^=q->random>>17;q->random^=q->random<<5;
        unsigned total=0;for(unsigned i=0;i<q->count;i++)if(q->remaining&(1u<<i))total++;
        unsigned pick=q->random%total,index=0;
        for(;index<q->count;index++)if(q->remaining&(1u<<index)){if(!pick)break;pick--;}
        q->remaining&=~(1u<<index);
        if(q->length==QM_TRACKS){memmove(q->history,q->history+1,(QM_TRACKS-1)*sizeof(unsigned));q->length--;}
        q->history[q->length++]=index;q->position=q->length-1;return q->current=index;
    }
    if(action==QM_QUEUE_PREVIOUS){if(q->current)return --q->current;if(q->mode!=QM_PLAY_ORDER)return q->current=q->count-1;}
    else {if(q->current+1<q->count)return ++q->current;if(q->mode!=QM_PLAY_ORDER)return q->current=0;}
    return QM_TRACKS;
}
