#define _POSIX_C_SOURCE 200809L
#define _GNU_SOURCE
#include <SDL.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

enum { kCapacity = 4096 };
static double bind_ms[kCapacity], detach_ms[kCapacity];
static size_t bind_count, detach_count;

static double elapsed_ms(struct timespec before, struct timespec after) {
  return (after.tv_sec - before.tv_sec) * 1000.0 +
         (after.tv_nsec - before.tv_nsec) / 1000000.0;
}

int SDL_GL_MakeCurrent(SDL_Window *window, SDL_GLContext context) {
  static int (*next)(SDL_Window *, SDL_GLContext);
  if (!next) {
    next = (int (*)(SDL_Window *, SDL_GLContext))dlsym(RTLD_NEXT,
                                                       "SDL_GL_MakeCurrent");
    if (!next) abort();
  }
  struct timespec before, after;
  clock_gettime(CLOCK_MONOTONIC, &before);
  const int result = next(window, context);
  clock_gettime(CLOCK_MONOTONIC, &after);
  double *values = context ? bind_ms : detach_ms;
  size_t *count = context ? &bind_count : &detach_count;
  if (*count >= kCapacity) abort();
  values[(*count)++] = elapsed_ms(before, after);
  return result;
}

__attribute__((destructor)) static void report(void) {
  fprintf(stderr, "SDL_CONTEXT_TIMING_JSON {\"bind_ms\":[");
  for (size_t i = 0; i < bind_count; ++i)
    fprintf(stderr, "%s%.6f", i ? "," : "", bind_ms[i]);
  fprintf(stderr, "],\"detach_ms\":[");
  for (size_t i = 0; i < detach_count; ++i)
    fprintf(stderr, "%s%.6f", i ? "," : "", detach_ms[i]);
  fprintf(stderr, "]}\n");
}
