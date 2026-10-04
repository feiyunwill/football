// Diagnostic-only interposer: time actual SDL_GL_SwapWindow calls.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

typedef void (*SwapWindow)(void*);
static _Atomic unsigned count = 0;
static double samples_ms[1024];

static double elapsed_ms(struct timespec before, struct timespec after) {
  return (double)(after.tv_sec - before.tv_sec) * 1000.0 +
         (double)(after.tv_nsec - before.tv_nsec) / 1000000.0;
}

void SDL_GL_SwapWindow(void* window) {
  static SwapWindow actual = NULL;
  if (!actual) {
    actual = (SwapWindow)dlsym(RTLD_NEXT, "SDL_GL_SwapWindow");
    if (!actual) abort();
  }
  struct timespec before, after;
  clock_gettime(CLOCK_MONOTONIC_RAW, &before);
  actual(window);
  clock_gettime(CLOCK_MONOTONIC_RAW, &after);
  unsigned index = atomic_fetch_add(&count, 1);
  if (index < 1024) samples_ms[index] = elapsed_ms(before, after);
}

static int compare_double(const void* left, const void* right) {
  double a = *(const double*)left, b = *(const double*)right;
  return (a > b) - (a < b);
}

__attribute__((destructor)) static void write_report(void) {
  const char* path = getenv("FOOTBALL_SWAP_TIMING_OUTPUT");
  if (!path) return;
  FILE* output = fopen(path, "w");
  if (!output) return;
  unsigned total = atomic_load(&count);
  unsigned stored = total < 1024 ? total : 1024;
  double ordered[1024];
  for (unsigned i = 0; i < stored; ++i) ordered[i] = samples_ms[i];
  qsort(ordered, stored, sizeof(double), compare_double);
  double p50 = stored ? ordered[(stored + 1) / 2 - 1] : 0;
  double p95 = stored ? ordered[(95 * stored + 99) / 100 - 1] : 0;
  fprintf(output, "{\"calls\":%u,\"stored\":%u,\"p50_ms\":%.6f,"
                  "\"p95_ms\":%.6f,\"samples_ms\":[",
          total, stored, p50, p95);
  for (unsigned i = 0; i < stored; ++i)
    fprintf(output, "%s%.6f", i ? "," : "", samples_ms[i]);
  fprintf(output, "]}\n");
  fclose(output);
}
