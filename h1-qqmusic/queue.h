#ifndef H1_QM_QUEUE_H
#define H1_QM_QUEUE_H
#include "core.h"
enum {QM_PLAY_ORDER,QM_PLAY_LIST_LOOP,QM_PLAY_SINGLE_LOOP,QM_PLAY_SHUFFLE,QM_PLAY_MODES};
enum {QM_QUEUE_PREVIOUS=-1,QM_QUEUE_NEXT=1,QM_QUEUE_ENDED=2};
typedef struct {
    unsigned count,current,mode,remaining,history[QM_TRACKS],length,position;
    uint32_t random;
} qm_queue_policy;
void qm_queue_begin(qm_queue_policy *,unsigned,unsigned,unsigned,uint32_t);
void qm_queue_mode(qm_queue_policy *,unsigned);
/* QM_TRACKS means a boundary: no song is changed. */
unsigned qm_queue_move(qm_queue_policy *,int);
const char *qm_queue_label(unsigned);
#endif
