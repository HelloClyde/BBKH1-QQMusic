#ifndef H1BILI_APP_H
#define H1BILI_APP_H
#include "core.h"
#include <stdint.h>
extern char bili_message[160];
extern volatile uint32_t bili_state[16];
extern int bili_cancelled;
void bili_paint(void);
void bili_idle(void *);
int bili_next_key(void);
int bili_net_open(void);
void bili_net_close(void);
void bili_net_cancel_reset(void);
int bili_net_json(const char *,char **,size_t *);
int bili_net_get(const char *,unsigned,char **,size_t *);
int bili_net_range(const char *,const char *,uint32_t,uint32_t,uint32_t,uint8_t *);
int bili_net_stream_read(const char *,uint32_t,uint32_t,uint32_t,uint8_t *);
void bili_net_stream_close(void);
#define BILI_BG_JOBS 3u
int bili_net_bg_begin(unsigned,const char *,char *,unsigned);
void bili_net_bg_poll(void);
int bili_net_bg_result(unsigned,unsigned *);
void bili_net_bg_stop(void);
uint32_t bili_net_features(void);
int bili_net_compute_rpc(unsigned,const void *,unsigned,void *,unsigned,unsigned *);
int bili_search_url(const char *,unsigned,char url[401]);
typedef struct {unsigned ready,playing,eof,error,width,height,frames,ms,audio;} bili_play_state;
extern bili_play_state bili_play;
extern uint8_t *bili_rgba;
int bili_player_open(const bili_media *);
void bili_player_step(void);
void bili_player_toggle(void);
void bili_player_close(void);
int bili_player_seek(int seconds);
extern volatile uint32_t bili_video_sync_mode,bili_video_sync_state[24];
void bili_player_set_sync(unsigned mode);
void bili_covers_reset(void);
int bili_cover_load(unsigned,const char *);
int bili_cover_start(unsigned,const char *);
int bili_cover_step(void);
void bili_cover_cancel(void);
const uint16_t *bili_cover_get(unsigned);
extern volatile uint32_t bili_cover_state[8];
/* Render 0: retained reference; 1: fused CPU; 2: fused + bounded MXU rows. */
extern volatile uint32_t bili_render_mode;
extern unsigned bili_active_render_mode,bili_frame_width,bili_frame_height;
extern uint16_t bili_frame_pixels[480*272];
#endif
