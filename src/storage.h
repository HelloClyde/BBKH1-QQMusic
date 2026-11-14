#ifndef QM_STORAGE_H
#define QM_STORAGE_H
/* A:\飞天音乐. Device filesystem paths are GBK, not UTF-8 string literals. */
#define QM_CONFIG_DIR "A:\\\xb7\xc9\xcc\xec\xd2\xf4\xc0\xd6"
#define QM_MODE_PATH QM_CONFIG_DIR "\\QQMusic.cfg"
#define QM_LEGACY_MODE "A:\\QQMusic.cfg"
void qm_storage_init(void);
void qm_auth_path(unsigned index,int legacy,char out[64]);
#endif
