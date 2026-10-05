// Diagnostic-only interposer for comparing SDL presentation interval modes.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

void *SDL_GL_CreateContext(void *window) {
  void *(*create)(void *) = dlsym(RTLD_NEXT, "SDL_GL_CreateContext");
  int (*set_interval)(int) = dlsym(RTLD_NEXT, "SDL_GL_SetSwapInterval");
  int (*get_interval)(void) = dlsym(RTLD_NEXT, "SDL_GL_GetSwapInterval");
  if (!create || !set_interval || !get_interval) abort();
  void *context = create(window);
  if (context) {
    const char *value = getenv("FOOTBALL_DIAGNOSTIC_SWAP_INTERVAL");
    if (value) {
      char *end = NULL;
      long requested = strtol(value, &end, 10);
      if (*end || requested < -1 || requested > 1) abort();
      int result = set_interval((int)requested);
      fprintf(stderr, "swap_interval_probe requested=%ld result=%d actual=%d\n",
              requested, result, get_interval());
    }
  }
  return context;
}
