#ifndef QM_IMAGES_H
#define QM_IMAGES_H
#include <stdint.h>
/* Bounded JPEG/PNG -> caller-owned RGB565; <=256KiB input, <=480x272 output. */
int qm_image_decode(const unsigned char *,unsigned,uint16_t **,unsigned *,unsigned *,unsigned,unsigned);
#endif
