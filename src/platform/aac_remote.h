#ifndef QM_AAC_REMOTE_H
#define QM_AAC_REMOTE_H
#include <stdint.h>
extern volatile uint32_t qm_aac_enable,qm_aac_state[16];
int qm_aac_open(const uint8_t *,unsigned);
int qm_aac_push(const uint8_t *,unsigned,uint32_t);
int qm_aac_read(uint8_t *,unsigned,unsigned *);
int qm_aac_reset(void);
int qm_aac_finish(void);
int qm_aac_eof(void);
void qm_aac_close(void);
/* Optional backpressure progress: may READ PCM and return bytes drained.
 * Return zero while the native PCM ring is full, or a negative fatal error.
 * The callback must not PUSH/RESET/CLOSE the session. CLOSE clears it. */
void qm_aac_set_progress(int (*)(void *),void *);
#endif
