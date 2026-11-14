#include "storage.h"
#include "h1_sdk.h"
#include <stdio.h>
void qm_storage_init(void)
{
    static int attempted;
    /* Existing-directory errors are harmless; the following verified writes
       detect a missing/read-only directory without falling back to root. */
    if(!attempted){attempted=1;(void)h1_mkdir(QM_CONFIG_DIR);}
}
void qm_auth_path(unsigned index,int legacy,char out[64])
{snprintf(out,64,"%s\\QQMusic.auth%u",legacy?"A:":QM_CONFIG_DIR,index);}
