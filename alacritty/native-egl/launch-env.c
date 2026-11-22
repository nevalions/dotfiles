#include <stdlib.h>
#include <string.h>
#include <unistd.h>

__attribute__((constructor)) static void restore_environment(void)
{
    const char *was_set = getenv("_ALACRITTY_EGL_PRELOAD_WAS_SET");
    const char *previous = getenv("_ALACRITTY_EGL_RESTORE_PRELOAD");
    if (was_set == NULL)
        return;

    int result;
    if (strcmp(was_set, "1") == 0)
        result = setenv("LD_PRELOAD", previous != NULL ? previous : "", 1);
    else
        result = unsetenv("LD_PRELOAD");
    if (result != 0)
        _exit(127);
    if (unsetenv("_ALACRITTY_EGL_PRELOAD_WAS_SET") != 0 ||
        unsetenv("_ALACRITTY_EGL_RESTORE_PRELOAD") != 0)
        _exit(127);
}
