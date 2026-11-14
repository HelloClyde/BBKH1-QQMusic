/* Reuse the tested generic AAC client without linking Bilibili UI or routes. */
#define bili_net_features qm_net_features
#define bili_net_compute_rpc qm_net_compute_rpc
#define bili_cancelled qm_cancelled
#define bili_idle qm_idle
#include "../h1-bilibili/audio_remote.c"
