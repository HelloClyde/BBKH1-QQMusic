#ifndef H1_QM_CORE_H
#define H1_QM_CORE_H
#include <stddef.h>
#include <stdint.h>
#define QM_TRACKS 12u
#define QM_LINES 160u
enum {QM_RIGHTS_MASK=3u,QM_RIGHTS_MEMBER=1u,QM_RIGHTS_UNKNOWN=2u,QM_RIGHTS_PLAYABLE=4u};
enum {QM_VIEW_LIST,QM_VIEW_PLAYER,QM_VIEW_ACCOUNT,QM_VIEW_HOME};
#define QM_KEY_HOME 500
typedef struct {char mid[15],media[15],album[15],title[160],artist[128];unsigned seconds,paid;} qm_track;
typedef struct {qm_track tracks[QM_TRACKS];unsigned count,page,total;} qm_list;
typedef struct {uint32_t ms;char text[112];} qm_line;
typedef struct {qm_line lines[QM_LINES];unsigned count;} qm_lyrics;
int qm_parse_list(const char *,size_t,qm_list *,char error[128]);
int qm_parse_url(const char *,size_t,const char *,char url[401],char error[128]);
int qm_parse_lyrics(const char *,size_t,qm_lyrics *);
int qm_search_url(const char *,unsigned,int,char url[401]);
int qm_vkey_body(const qm_track *,uint32_t,char body[640]);
int qm_cover_url(const qm_track *,char url[401]);
unsigned qm_lyric_at(const qm_lyrics *,uint32_t);
void qm_set_parse_progress(void (*)(void));
#endif
