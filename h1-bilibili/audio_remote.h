#ifndef BILI_AUDIO_REMOTE_H
#define BILI_AUDIO_REMOTE_H
#include <stdint.h>
extern volatile uint32_t bili_audio_remote_enable,bili_audio_remote_state[16];
int bili_audio_remote_open(const uint8_t *,unsigned);
int bili_audio_remote_push(const uint8_t *,unsigned,uint32_t);
int bili_audio_remote_read(uint8_t *,unsigned,unsigned *);
int bili_audio_remote_reset(void);
int bili_audio_remote_finish(void);
int bili_audio_remote_eof(void);
void bili_audio_remote_close(void);
/* Optional backpressure progress: may READ PCM and return bytes drained.
 * Return zero while the native PCM ring is full, or a negative fatal error.
 * The callback must not PUSH/RESET/CLOSE the session. CLOSE clears it. */
void bili_audio_remote_set_progress(int (*)(void *),void *);
#endif
