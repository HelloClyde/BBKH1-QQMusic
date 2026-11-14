#ifndef H1BILI_CORE_H
#define H1BILI_CORE_H
#include <stdint.h>
#include <stddef.h>
#define BILI_ITEMS 12
#define BILI_PARTS 32
typedef struct {char bvid[13],title[192],owner[80],duration[24],cover[401];} bili_item;
typedef struct {char cid[24],title[128];unsigned duration;} bili_part;
typedef struct {
    bili_item items[BILI_ITEMS];unsigned count,page,pages;
} bili_list;
typedef struct {
    char bvid[13],title[192],owner[80],description[512];
    bili_part parts[BILI_PARTS];unsigned count,total_parts,duration;
} bili_detail;
typedef struct {char urls[3][2049];unsigned count;uint32_t size,duration_ms,quality;} bili_media;
int bili_bvid(const char *input,char out[13]);
int bili_parse_list(const char *,size_t,bili_list *,char error[128]);
int bili_parse_detail(const char *,size_t,bili_detail *,char error[128]);
int bili_parse_media(const char *,size_t,bili_media *,char error[128]);
int bili_quote(const char *,char *,size_t);
int bili_parse_wbi(const char *,size_t,char mixin[33]);
uint32_t bili_parse_clock(const char *,size_t);
int bili_thumbnail_url(const char *,char out[401]);
#endif
