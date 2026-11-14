#ifndef H1_NEWS_IMAGE_H
#define H1_NEWS_IMAGE_H
#include <stdint.h>
/* Returned RGB565 storage belongs to the caller. 0 succeeds, -1 rejects.
 * Inputs <=256KiB, dimensions <=4096, output <=480x272. */
int news_image_decode(const unsigned char *data,unsigned size,uint16_t **out,
                      unsigned *width,unsigned *height,unsigned maxw,unsigned maxh);
/* Only the verified IT Home image hosts use their public thumbnail endpoint.
 * Other image URLs remain unchanged. 1 succeeds, 0 rejects an invalid URL. */
int news_image_url(const char *source,char out[401]);
#endif
